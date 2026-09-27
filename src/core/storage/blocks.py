# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""块面的存储实现：**一个块落成两条记录**。

设计见 `docs/architecture/storage-design.md` §4、§8.2。分层上它坐在载体之上、领域之下：

    领域结构 → 块（本模块）→ 记录（`vault`）→ 载体（`io`）

**两条记录的由来**：body 有自己的身份，故它自己一条记录；块承载 body，故块记录里带着
**指向该身份的凭证**：

    内容记录  `value_uuid` 随机分配、`value_hash` = 载荷摘要   → 同内容只存一份
    块记录    `value_uuid` = 块的身份、`value_hash` = 本记录载荷摘要；
              载荷里放 `attrs` / `config` / `author` 与 **`body_addr`（body 地址）**

于是读回是"两条一拼"：块记录 → 载荷里的 `body_addr` → 内容记录 → body 字节 → `Block.decode`。

四处口径写明：

- **指针在载荷里，不在 ID 里**：记录层的自校验要求"`value_hash` 恒等于本记录载荷摘要"
  （§5.3，`Record.decode` 会当场核对），故块记录的 ID 无法同时承载 body 的摘要。
  设计篇 §3.2.1 原先写作"一格两用"（指向身份 ＋ 内容判重），此处按**自校验优先**改为
  "ID 管自身、载荷管指针"；指针仍在载荷里，故顺扫照样能还原它（档一可重建不受影响）；
- **块记录的判据是"载荷里有 `body_addr`"**：这是本层的载荷格式，不是猜测；内容记录的载荷
  就是内容本身，不会有这个字段。要不要把它提升成索引里的一列（换来"哪些块共用这份内容"
  一次查得到、列举时不必读载荷），是表声明的字段问题，见设计篇 §12；
- **类型不进记录头**，由程序按 ID 给出（§3.3 第 5 条）：块记录的类型落在索引库的 `kind` 列，
  不认识的类型**降级读回**为裸块，不抛错、不丢弃。故重建补回的块行类型为空，
  但**仍然是块**（判据在载荷里，不必靠列）；
- **本模块只做翻译**：分片（大 body 切成 PART + INDEX）尚未接进来，等大正文落地时补；
  事务与压实同样不在这一层（§12）。

与 `block.py` 的分工：那个文件是**块这个类本身**（字段、编解码、类型登记），
本文件是**块怎么落成记录**。名字相邻，但不是一回事。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from core.types import (
    CorruptObjectError,
    Id,
    InvalidIdError,
    KindMismatchError,
    ObjectNotFoundError,
    ValueHash,
    ValueUuid,
    now_ms,
    type_name,
)

from .block import Block, canonical, decode_canonical
from .record import Record
from .vault import DEFAULT_BUCKET, Vault

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator
    from pathlib import Path

    from .index import RebuildPlan


class BlockStore:
    """块面的存储：一块进、一块出（内部是两条记录）。

    它是**领域唯一该看见的存储面**：领域只认识块，不认识记录、槽、载体与桶。
    库由 :class:`Vault` 持有，故多桶对这里是透明的——只多一个"写进哪个桶"的参数。
    """

    def __init__(self, vault: Vault) -> None:
        self.vault = vault

    # ---- 生命周期 ----
    @classmethod
    def open(
        cls,
        path: Path | str,
        *,
        rebuild: RebuildPlan | None = None,
        pack_max_bytes: int | None = None,
    ) -> BlockStore:
        """开（或建）一个库并把它接到块面上。"""
        return cls(Vault.open(path, rebuild=rebuild, pack_max_bytes=pack_max_bytes))

    def close(self) -> None:
        """关闭底层索引库连接。"""
        self.vault.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- 写 ----
    def store(self, block: Block, *, bucket: str = DEFAULT_BUCKET) -> Block:
        """写入整个块；返回同一个块（时间与大小就地刷新）。

        顺序是**先内容、后块记录**：块记录指向的 body 必须先存在，
        否则中途失败会留下一个指向空处的块记录。
        """
        block.validate()
        body = block.encode_body()
        digest = ValueHash.of(body)
        if self._content_of(digest) is None:
            self.vault.put(Record(id=Id.new(body), payload=body), bucket=bucket)

        now = now_ms()
        existing = self.vault.index.record_row(block.id)
        created = int(existing["created"]) if existing is not None else (block.created or now)
        blob = canonical(_blob_of(block, digest))
        ident = Id(
            value_uuid=ValueUuid.parse(block.id),
            value_hash=ValueHash.of(blob),
            issued=created,
        )
        self.vault.put(Record(id=ident, payload=blob), kind=type_name(block.type), bucket=bucket)

        block.checksum = str(digest)
        # 落盘时刻以索引行为准（它是"写进去"这件事的真源），故写完再读回来贴一次：
        # 自己在内存里另算一个 now 只会与行里差那么一毫秒，然后两边都自称是"创建时间"。
        row = self.vault.index.record_row(block.id)
        return block if row is None else self._finish(block, row)

    def drop(self, oid: str) -> bool:
        """摘掉一个块；返回它此前是否存在。

        **只摘定位行**：body 与记录字节留在载体里，等压实回收（与"物理坐标是投影"同一口径）。
        """
        if self.vault.index.record_row(str(oid)) is None:
            return False
        self.vault.index.remove_record(str(oid))
        self.vault.index.commit()
        return True

    # ---- 读 ----
    def fetch(self, oid: str) -> Block:
        """按身份读回一个块；类型按索引里的 ``kind`` 还原，不认识即降级为裸块。"""
        row = self.vault.index.record_row(str(oid))
        if row is None:
            raise ObjectNotFoundError(str(oid))
        return self._finish(self._block_of(self.vault.get(str(oid)), kind=str(row["kind"])), row)

    def get[T: Block](self, cls: type[T], oid: str) -> T:
        """按身份读回并校验类型。"""
        block = self.fetch(str(oid))
        if not isinstance(block, cls):
            raise KindMismatchError(f"{oid} 不是 {cls.__name__}（实际 {block.type}）")
        return block

    def read(self, oid: str) -> bytes:
        """读回块的**主体字节**（结构化 body 无字节视图，照旧显式报错）。"""
        return self.fetch(str(oid)).read()

    def has(self, oid: str) -> bool:
        """这个身份在库里有没有定位行。"""
        return self.vault.index.record_row(str(oid)) is not None

    def iter_blocks(self) -> Iterator[Block]:
        """遍历全部块：读回每条记录，跳过内容记录。

        **一趟全读**：索引里放不下"标题 / 标签"（那是属性，不是定位信息），
        故列举块必须读回每条记录。要不要把属性投影进库是表声明的字段问题（§12）。

        内容缺了就**显式报错**，不跳过：一次列举悄悄少一个对象，比报错难查得多。
        """
        for _place, record in self.vault.records():
            if not _is_block(record):
                continue
            row = self.vault.index.record_row(str(record.id.value_uuid))
            kind = str(row["kind"]) if row is not None else ""
            block = self._block_of(record, kind=kind)
            yield block if row is None else self._finish(block, row)

    # ---- 内部 ----
    def _finish(self, block: Block, row: sqlite3.Row) -> Block:
        """把索引里那几项"不在记录头里"的元信息贴回块上。

        时间只存在于索引里（记录头不带时间，§3.5）；**大小另算**：
        `record.size` 是**记录字节数**（便于估算与巡检），块的 `size` 是**主体字节数**，
        两个不同的东西共用一个名字，故不能互相赋值。
        """
        block.created = int(row["created"])
        block.updated = int(row["updated"])
        block.size = block.content_size()
        return block

    def _block_of(self, record: Record, *, kind: str) -> Block:
        """块记录 ＋ 它的内容记录 → 一个块。"""
        pointer = _body_pointer(record)
        if pointer is None:
            raise CorruptObjectError(
                f"这不是块记录（载荷里没有 body 地址）：{record.id.value_uuid}"
            )
        content = self._content_of(pointer)
        if content is None:
            raise CorruptObjectError(
                f"块的内容缺失：{record.id.value_uuid}（地址 {pointer}；可由巡检重建补回）"
            )
        blob = _decode_blob(record.payload)
        return Block.decode(
            content.payload,
            id=str(record.id.value_uuid),
            attrs=dict(blob.get("attrs") or {}),
            type=kind,
        )

    def _content_of(self, digest: ValueHash | str) -> Record | None:
        """按地址找**内容记录**；找不到即 ``None``。

        候选只可能来自 `value_hash` 索引：内容记录的身份就是该地址（载荷即内容）。
        块记录的 `value_hash` 是它自己载荷的摘要，与 body 地址撞上等于摘要碰撞，
        故这里只需在候选里排除块记录（判据与 :func:`_is_block` 同一处口径）。
        """
        target = ValueHash.parse(str(digest))
        for row in self.vault.index.find_by_hash(str(target)):
            record = self.vault.get(str(row["value_uuid"]))
            if not _is_block(record):
                return record
        return None

    def __repr__(self) -> str:
        return f"BlockStore({self.vault.root})"


def _is_block(record: Record) -> bool:
    """这条记录是不是**块记录**：载荷里带着 body 地址。

    这是本层**载荷格式**的判据（内容记录的载荷就是内容本身，不会有这个字段），
    也是"重建补回的块行照样认得出是块"的原因——它不依赖索引里的任何一列。
    """
    return _body_pointer(record) is not None


def _body_pointer(record: Record) -> ValueHash | None:
    """块记录载荷里的 ``body_addr``；不是块记录即 ``None``。"""
    try:
        raw: Any = decode_canonical(record.payload) if record.payload else None
    except Exception:  # noqa: BLE001 — 内容记录的载荷是任意字节，解不出属正常
        return None
    if not isinstance(raw, dict):
        return None
    return _digest_or_none(raw.get("body_addr"))


def _digest_or_none(value: Any) -> ValueHash | None:
    """把载荷里的地址字段解析成摘要；不是合法摘要即当作"没有指针"。"""
    if value is None:
        return None
    try:
        return ValueHash.parse(str(value))
    except InvalidIdError:
        return None


def _blob_of(block: Block, digest: ValueHash) -> dict[str, Any]:
    """块记录的载荷：随块行单独存的东西 ＋ **指向 body 的地址**。"""
    return {
        "attrs": block.attrs,
        "config": block.config,
        "author": block.author,
        "body_addr": str(digest),
    }


def _decode_blob(payload: bytes) -> dict[str, Any]:
    """解的块记录载荷；解不出即报损坏，不猜。"""
    try:
        raw: Any = decode_canonical(payload) if payload else {}
    except Exception as exc:
        raise CorruptObjectError("块记录的属性段解析失败") from exc
    if not isinstance(raw, dict):
        raise CorruptObjectError(f"块记录的属性段不是映射：{type(raw).__name__}")
    return {str(key): value for key, value in raw.items()}


__all__ = ["BlockStore"]
