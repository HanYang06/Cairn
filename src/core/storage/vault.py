# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""桶与多桶：**一个库 ＋ 若干桶**，引擎视角下只有一块盘。

设计见 `docs/architecture/storage-design.md` §6、§7。两层各管一件事：

- :class:`Bucket` —— 一个桶：``<vault>/<桶名>/packs/`` 下的一串载体。
  追加记录、按物理坐标读回、顺扫全部记录。**桶目录即存在证明**，本层不记任何状态；
- :class:`Vault` —— 多桶：一个库**只有一个索引库**（``catalog.db``），桶名是库里的一列。
  它只需回答"这个 ID 在哪个桶"，故多桶对上层只是一次分组，不带来第二个库。

四条纪律：

1. **物理坐标是投影，不是事实**：记录内容不带坐标，索引里的 ``(桶, 载体, 槽区间)``
   只是"少读一遍"的映射，丢了可以顺扫重建（§5.2、§8.5 档一）；
2. **先落字节、后记目录**：索引行指向的位置必然已经存在；反过来只会留下空洞，
   要到读的时候才发现。中途失败留下的孤儿字节由 :meth:`Vault.rebuild_records` 收编；
3. **命名无语义**：载体名取随机串（§5.1），故"载体序号"这种概念不存在，
   也就不会有人把顺序当含义用；
4. **配置只在写入的这一刻读**：槽长随载体走（写进文件头，§5.5），
   封口线是策略（每次写入按当前值判）——两者性质不同，故取用方式也不同。

与旧层的关系：旧 ``core.storage.Bucket``（配 ``catalog``）是待退役的一层（§11 第 4 步），
新层先在 ``core.storage.vault`` 落地，接线与旧层退役随后进行。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Self

from core.types import (
    BucketExistsError,
    BucketNotFoundError,
    CairnError,
    CorruptObjectError,
    ObjectNotFoundError,
    SlotRange,
    StorageError,
    now_ms,
)

from .index import INDEX_NAME, Index, RebuildPlan
from .io import CarrierFile
from .record import Record

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator

DEFAULT_BUCKET = "main"
"""默认桶名：不带桶名的写入落这里。"""

PACKS_DIR = "packs"
"""桶内的载体目录名。**它是不是目录，就是"这是不是一个桶"的判据**。"""

PACK_SUFFIX = ".pack"
"""载体文件后缀。"""

PACK_NAME_BYTES = 8
"""载体名取的随机字节数（8 字节 → 16 位十六进制）。"""

_BAD_NAME_CHARS = frozenset('<>:"/\\|?*')


class BucketRole(Enum):
    """桶的形态（登记列 ``bucket.role`` 的取值域）。"""

    MAIN = "main"
    """主桶：常规写入落这里。"""

    ARCHIVE = "archive"
    """归档桶：以只读为主。"""

    TRANSIENT = "transient"
    """短命桶：并发期承接写入，合并后销毁（**预留**：合并尚未实现，§7）。"""


class BucketState(Enum):
    """桶的挂载状态（登记列 ``bucket.state`` 的取值域）。"""

    MOUNTED = "mounted"
    """已挂载：参与读写。"""

    MERGED = "merged"
    """已并入别处（**预留**：合并尚未实现）。"""


@dataclass(frozen=True, slots=True)
class Placement:
    """一条记录的**物理坐标**：桶 ＋ 载体 ＋ 槽区间。

    属投影、不是事实（§5.2）：压缩、合并与搬移只改这份映射，不改记录携带的内容。
    故它可以随时由顺扫重算，也正因如此才敢存在索引里。
    """

    bucket: str
    """所在桶名。"""

    pack: str
    """所在载体名（文件名，不含目录）。"""

    span: SlotRange
    """所占槽区间（含槽内偏移，三项齐全才与字节偏移一一对应）。"""

    size: int = 0
    """记录字节数（便于估算与巡检；长度本身仍由槽数与记录头收敛）。"""


def _check_bucket_name(name: str) -> str:
    """桶名校验：它会成为目录名，故不许带路径分隔符与平台保留字符。

    索引里的桶名是**数据**，读路径会拿它拼目录；不挡住 ``../`` 就等于把越界读的口子留着。
    """
    if not name or name in {".", ".."}:
        raise StorageError(f"桶名非法: {name!r}")
    if set(name) & _BAD_NAME_CHARS or any(char < " " for char in name):
        raise StorageError(f"桶名含平台非法字符: {name!r}")
    if name != name.strip() or name.endswith("."):
        raise StorageError(f"桶名不得以空白或点收尾: {name!r}")
    return name


def _pack_path(packs_dir: Path, name: str) -> Path:
    """载体路径：名字必须是一个**纯文件名**（索引里的脏名字不得越出桶目录）。"""
    if not name or name != Path(name).name or name in {".", ".."}:
        raise StorageError(f"载体名非法: {name!r}")
    return packs_dir / name


def _configured_pack_max_bytes() -> int:
    """向配置要封口线（每次写入都按当前值判）。

    **先引入声明模块再取值**：配置引擎按"谁声明谁报到"工作，没导入过的声明它不认识。
    值文件可被用户编辑，故在这里校验成整数——把字符串带进比较表达式，
    报出来的是难以定位的 ``TypeError``。
    """
    from . import conf as _declared  # noqa: PLC0415 — 先让声明报到

    value: object = _declared.conf.pack_max_bytes
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CairnError(f"配置 storage.pack.max_bytes 必须是正整数，得到 {value!r}")
    return value


def _span_of(row: sqlite3.Row) -> SlotRange:
    """索引行里的槽区间（列名与槽区间的对应只在这里落一次）。"""
    return SlotRange(
        start=int(row["slot_start"]),
        count=int(row["slot_count"]),
        head=int(row["slot_head"]),
    )


def _placement_of(row: sqlite3.Row) -> Placement:
    """索引行 → 物理坐标。"""
    return Placement(
        bucket=str(row["bucket"]),
        pack=str(row["pack"]),
        span=_span_of(row),
        size=int(row["size"]),
    )


class Bucket:
    """一个桶：``<vault>/<桶名>/packs/`` 下的一串载体。

    **无状态**：桶的形态、状态与时刻都记在索引库里（登记），本类只按目录与文件说话。
    故桶目录拷到哪里都成立，索引库丢了也能顺扫回来。
    """

    def __init__(self, root: Path | str, *, pack_max_bytes: int | None = None) -> None:
        self.root = Path(root)
        self.packs_dir = self.root / PACKS_DIR
        self._pack_max_bytes = pack_max_bytes

    # ---- 生命周期 ----
    @classmethod
    def create(cls, root: Path | str, *, pack_max_bytes: int | None = None) -> Bucket:
        """建桶：目录已存在即拒（**不接管已有目录**）。"""
        target = Path(root)
        if target.exists():
            raise BucketExistsError(f"桶已存在: {target}")
        target.mkdir(parents=True)
        (target / PACKS_DIR).mkdir()
        return cls(target, pack_max_bytes=pack_max_bytes)

    @classmethod
    def open(cls, root: Path | str, *, pack_max_bytes: int | None = None) -> Bucket:
        """打开桶：目录必须在（**只读不建**；建目录是 :meth:`create` 的事）。"""
        target = Path(root)
        if not target.is_dir():
            raise BucketNotFoundError(f"桶不存在: {target}")
        return cls(target, pack_max_bytes=pack_max_bytes)

    @property
    def name(self) -> str:
        """桶名：即目录名，**桶的地址**就是它。"""
        return self.root.name

    @property
    def pack_max_bytes(self) -> int:
        """封口线（未显式给定时向配置要）。"""
        if self._pack_max_bytes is not None:
            return self._pack_max_bytes
        return _configured_pack_max_bytes()

    # ---- 载体 ----
    def packs(self) -> tuple[CarrierFile, ...]:
        """桶内全部载体（按名排序；**真源是文件系统**，没有登记表）。"""
        if not self.packs_dir.is_dir():
            return ()
        return tuple(
            CarrierFile.open(path) for path in sorted(self.packs_dir.glob(f"*{PACK_SUFFIX}"))
        )

    def new_pack(self) -> CarrierFile:
        """开一个新载体；名字取随机串（无语义、无顺序号，§5.1）。

        随机名不是风格问题：序号名在压实之后会被重用，而重用的名字会让**过期的索引行
        指向另一个文件**；随机名只会指向不存在的文件，于是坏得看得见。
        """
        self.packs_dir.mkdir(parents=True, exist_ok=True)
        while True:
            target = self.packs_dir / f"{secrets.token_hex(PACK_NAME_BYTES)}{PACK_SUFFIX}"
            if not target.exists():
                return CarrierFile.create(target)

    def active(self) -> CarrierFile:
        """取活跃载体：**有空间的最满的那一个**；一个都没有就新开。

        为什么"最满"是确定的答案：写入纪律是"写到满才换"，故手上那个必然是最满的。
        封口线被调大之后可能不止一个载体有空间，此时按同一判据仍然只有一个答案，
        不依赖时间戳，也不依赖名字顺序（名字本就是随机的）。
        """
        limit = self.pack_max_bytes
        candidates = [carrier for carrier in self.packs() if carrier.used_bytes < limit]
        if not candidates:
            return self.new_pack()
        return max(candidates, key=lambda carrier: (carrier.used_bytes, carrier.path.name))

    # ---- 记录 ----
    def append(self, record: Record) -> Placement:
        """把一条记录追加到活跃载体，返回**由实际写入位置算出**的物理坐标。

        写之前按该载体的槽长自检一次：槽算术的错误要挡在落盘之前，
        而不是等下次顺扫才发现对不上。
        """
        carrier = self.active()
        record.header(carrier.layout.slot_bytes).verify(carrier.layout)
        span = carrier.append(record)
        return Placement(bucket=self.name, pack=carrier.path.name, span=span, size=record.total_len)

    def read(self, pack: str, span: SlotRange) -> Record:
        """按物理坐标读回一条记录（载体名与槽区间都由索引给出）。"""
        path = _pack_path(self.packs_dir, pack)
        if not path.is_file():
            raise CorruptObjectError(f"载体缺失: {path}")
        carrier = CarrierFile.open(path)
        return Record.decode(carrier.read(span), carrier.layout)

    def records(self) -> Iterator[tuple[Placement, Record]]:
        """顺扫桶内全部载体（**不依赖索引**；重建与巡检的入口）。"""
        for carrier in self.packs():
            for span, record in carrier.scan():
                place = Placement(
                    bucket=self.name,
                    pack=carrier.path.name,
                    span=span,
                    size=record.total_len,
                )
                yield place, record

    def __repr__(self) -> str:
        return f"Bucket({self.name}@{self.root.parent})"


class Vault:
    """一个库：唯一索引库 ＋ 若干桶（**引擎视角下一块盘**）。

    用法::

        vault = Vault.open("vault")
        place = vault.put(record, kind="notedata")     # 先落字节，后记目录
        same = vault.get(record.id.value_uuid)         # 索引定位 → 读回记录

    桶按名字寻址（目录名即地址）。名字取人话（``main``）还是取 ID 形态，
    对路径式查询没有区别——两跳都是查表：先查桶，再按槽区间读块。
    """

    def __init__(self, root: Path | str, *, pack_max_bytes: int | None = None) -> None:
        self.root = Path(root)
        self.index = Index.open(self.root / INDEX_NAME)
        self._pack_max_bytes = pack_max_bytes

    # ---- 生命周期 ----
    @classmethod
    def open(
        cls,
        root: Path | str,
        *,
        rebuild: RebuildPlan | None = None,
        pack_max_bytes: int | None = None,
    ) -> Vault:
        """打开库（索引库不存在即建）；**开库即对齐声明**。

        对齐只在开库时发生（§8.4）：热路径上反复执行 DDL 与提交是设计事故。
        破坏性差异**默认拒绝**，须由调用方显式给出 :class:`RebuildPlan`。
        """
        target = Path(root)
        target.mkdir(parents=True, exist_ok=True)
        vault = cls(target, pack_max_bytes=pack_max_bytes)
        remaining = vault.index.align(rebuild=rebuild)
        if remaining:
            vault.close()
            raise CairnError(f"索引库对齐后仍有差异（不假装成功）：{remaining}")
        return vault

    def close(self) -> None:
        """关闭索引库连接。"""
        self.index.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def verify(self) -> None:
        """**不建表地**校验：库内记录的声明投影与程序当前声明是否一致（巡检用）。"""
        self.index.verify_declarations()

    # ---- 桶：目录是事实，登记是投影 ----
    def buckets(self) -> tuple[Bucket, ...]:
        """库里全部桶：vault 下**带 ``packs/`` 的直接子目录**。

        不认成桶的目录一律不碰（库里还会有别的东西）；认出桶靠的是"桶的形状"，
        故空桶也算——建桶时就带上了 ``packs/``。
        """
        if not self.root.is_dir():
            return ()
        return tuple(
            Bucket.open(child, pack_max_bytes=self._pack_max_bytes)
            for child in sorted(self.root.iterdir())
            if (child / PACKS_DIR).is_dir()
        )

    def bucket(self, name: str = DEFAULT_BUCKET, *, role: BucketRole = BucketRole.MAIN) -> Bucket:
        """取一个桶（不在就建，并把登记行补进索引库）。"""
        _check_bucket_name(name)
        path = self.root / name
        if not (path / PACKS_DIR).is_dir():
            if path.exists():
                raise StorageError(f"{path} 已存在但不是桶（缺 {PACKS_DIR}/）")
            Bucket.create(path, pack_max_bytes=self._pack_max_bytes)
        found = Bucket.open(path, pack_max_bytes=self._pack_max_bytes)
        self.register(found, role=role)
        return found

    def register(
        self,
        bucket: Bucket,
        *,
        role: BucketRole = BucketRole.MAIN,
        state: BucketState = BucketState.MOUNTED,
    ) -> bool:
        """把一个桶登记进索引库；**已在册即不动**，返回这次是否新登记。

        已在册的一律不改写：登记记的是"第一次见到它"的时刻与形态，
        再取一次不该一并改成别的形态——改形态是显式动作。
        """
        known = self.index.conn.execute(
            "SELECT name FROM bucket WHERE name = ?", (bucket.name,)
        ).fetchone()
        if known is not None:
            return False
        self.index.conn.execute(
            "INSERT INTO bucket(name, role, state, created) VALUES(?, ?, ?, ?)",
            (bucket.name, role.value, state.value, now_ms()),
        )
        self.index.commit()
        return True

    def bucket_rows(self) -> list[sqlite3.Row]:
        """登记表里的全部桶行（**登记视图**；真源仍是目录）。"""
        return list(self.index.conn.execute("SELECT * FROM bucket ORDER BY name").fetchall())

    def reconcile(self) -> list[str]:
        """桶登记对账：目录里有的补登记，登记里有的**只报告不删**。

        返回"有登记、无目录"的桶名：多出的登记交由人工处置（与"多出的列不静默删除"同一口径）。
        """
        found = self.buckets()
        for bucket in found:
            self.register(bucket)
        names = {bucket.name for bucket in found}
        return sorted(
            str(row["name"]) for row in self.bucket_rows() if str(row["name"]) not in names
        )

    # ---- 记录：写入与读取 ----
    def put(self, record: Record, *, kind: str = "", bucket: str = DEFAULT_BUCKET) -> Placement:
        """写入一条记录，返回它的物理坐标。

        **先落字节、后记目录**：索引行指向的位置必然已经存在。
        反过来（先记目录再落字节）只会留下空洞，且要到读的时候才发现。
        中途失败留下的孤儿字节不影响正确性：顺扫即可发现它们（:meth:`rebuild_records`）。
        """
        target = self.bucket(bucket)
        place = target.append(record)
        self._write_row(place, record, kind=kind)
        self.index.commit()
        return place

    def placement(self, value_uuid: str) -> Placement | None:
        """按身份取物理坐标；没有即 ``None``（不抛错：调用方常要判存在）。"""
        row = self.index.record_row(value_uuid)
        return None if row is None else _placement_of(row)

    def get(self, value_uuid: str) -> Record:
        """按身份读回一条记录：索引定位 → 打开桶 → 按槽区间读。"""
        row = self.index.record_row(value_uuid)
        if row is None:
            raise ObjectNotFoundError(value_uuid)
        return self._read_row(row)

    def records(self, *, bucket: str = "") -> Iterator[tuple[Placement, Record]]:
        """顺扫记录：``bucket`` 给了就只扫那个桶，否则扫全部桶。"""
        targets = (self._open_bucket(bucket),) if bucket else self.buckets()
        for target in targets:
            yield from target.records()

    def rebuild_records(self) -> int:
        """档一重建：顺扫全部载体，把**缺失的定位行**补回索引库，返回补了几行。

        只补不覆盖：``kind`` 与落盘时刻都不在记录头里（类型由程序给出，§3.5），
        重扫无法还原它们，故已有的行一律不动——否则一次重建会把类型信息抹掉。
        清空重扫（权威重建）需要程序按 ID 给出类型，属 ID 专项的落点。
        """
        added = 0
        for place, record in self.records():
            if self.index.record_row(str(record.id.value_uuid)) is not None:
                continue
            # 记录头里有 ID 与签发时刻，故身份与 issued 能还原；类型与落盘时刻不能。
            self._write_row(place, record, created=0, updated=0)
            added += 1
        if added:
            self.index.commit()
        return added

    # ---- 内部 ----
    def _open_bucket(self, name: str) -> Bucket:
        """按名打开一个**已存在**的桶：读路径缺目录即报错，不悄悄建一个。"""
        _check_bucket_name(name)
        path = self.root / name
        if not (path / PACKS_DIR).is_dir():
            raise BucketNotFoundError(f"桶不存在: {path}")
        return Bucket.open(path, pack_max_bytes=self._pack_max_bytes)

    def _read_row(self, row: sqlite3.Row) -> Record:
        """按一条定位行读回记录。"""
        target = self._open_bucket(str(row["bucket"]))
        return target.read(str(row["pack"]), _span_of(row))

    def _write_row(
        self,
        place: Placement,
        record: Record,
        *,
        kind: str = "",
        created: int | None = None,
        updated: int | None = None,
    ) -> None:
        """写一条定位行：位置永远由载体的实际写入结果给出。

        改写已有行时**保留已有的类型与落盘时刻**：本次调用没带类型（如重建）不代表
        那个类型不存在，抹掉它就等于把信息丢掉。``issued`` 来自 ID 本身，不受此影响。
        """
        now = now_ms()
        value_uuid = str(record.id.value_uuid)
        existing = self.index.record_row(value_uuid)
        self.index.upsert_record(
            {
                "value_uuid": value_uuid,
                "value_hash": str(record.id.value_hash),
                "kind": kind or (str(existing["kind"]) if existing is not None else ""),
                "bucket": place.bucket,
                "pack": place.pack,
                "slot_start": place.span.start,
                "slot_head": place.span.head,
                "slot_count": place.span.count,
                "size": place.size,
                "issued": int(record.id.issued),
                "created": (
                    created
                    if created is not None
                    else (int(existing["created"]) if existing is not None else now)
                ),
                "updated": updated if updated is not None else now,
            }
        )

    def __repr__(self) -> str:
        return f"Vault({self.root})"


__all__ = [
    "DEFAULT_BUCKET",
    "PACKS_DIR",
    "PACK_SUFFIX",
    "Bucket",
    "BucketRole",
    "BucketState",
    "Placement",
    "Vault",
]
