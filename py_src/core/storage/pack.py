# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""载体:一个文件,内含等长格;**一格即一个槽**,槽头十六字节加内容.

一句话就说得完:**文件里是格,格是一个槽,块由若干槽拼成.**

本模块管三件事,多一件都不揽:

- **文件头**(24 字节):魔数与格长.故**载体自描述**——只凭这个文件就能算地址,
  不必问配置.格长随载体走:不同批次可以不同格长,各自照样精确算术定位;
- **槽**:槽头(槽种类 1 + crc32 校验和 4 + 内容长度 4 + 预留 7)加内容.
  一格的可用内容即**格长减 16**;内容超出即报错,不静默截断;
- **读写**:正文槽只追加,属性槽可原地覆盖.**唯一可变的事实是文件尾在哪**——
  没有空闲表,没有分配位图:槽号 < 文件尾格数即"写过",≥ 即"空闲".

**载体上不写一个字节的身份**:没有记录头,没有身份段,没有帧,没有版本组,
没有归属字段,没有墓碑.故载体只装值,**索引库装身份,位置与正文摘要**,
两者缺一,块都取不回来.顺扫仍然在,但它只服务诊断与回收.

**封口是策略,不是状态**:判据是"剩下的地方装不下下一格"(:attr:`Pack.sealed`),
文件里不留任何封印标记——故改封口线不会出现"标记与事实不符".

**读路径不建东西**:文件不在即报错,不新建一个空的顶上——空载体与"载体丢了"必须分得开.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, NamedTuple
from zlib import crc32

from core.exc import HubShapeError, SlotError, SlotFormatError, SlotTooLargeError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

MAGIC = b"CairnPk2"
"""载体魔数：末位是布局版本号。不符即报错，不作推断，也不当作"此处没有载体"。"""

HEADER_SIZE = 24
"""文件头长度（字节）：魔数 8 ＋ 格长 8 ＋ 预留 8。**它不必凑成整格**。"""

SLOT_HEAD_SIZE = 16
"""槽头长度（字节）：槽种类 1 ＋ crc32 4 ＋ 内容长度 4 ＋ 预留 7。"""

ATTR_SLOT = 1
"""槽种类：**属性槽**——装一个块的全部属性，可原地覆盖。"""

BODY_SLOT = 2
"""槽种类：**正文槽**——装正文分片，只追加。"""

EMPTY_SLOT = 0
"""没写过的格：槽种类为 0。它既不是属性槽也不是正文槽。"""

DEFAULT_MAX_BYTES = 2 * 1024**3
"""封口线：单个载体写满这个字节数就换新载体。只管"换不换文件"，不是硬上限。

它是**构造退路**（没给 `max_bytes` 时用它）；配置面那条默认值
（`core.storage.pack.max.byte`，声明处写的是同值的字面量）由
`tests/core/test_conf_projection.py` 盯着，两处分叉即失败。
"""

_HEADER = struct.Struct(">8sQQ")
_SLOT = struct.Struct(">BII7s")
"""槽头：槽种类 1 ＋ crc32 4 ＋ 内容长度 4 ＋ 预留 7。

预留那 7 字节**如实写零**（不写成对齐补白）：它是留给将来加字段的那一段，
写零才有"这一段还没用"的读法。
"""

if _SLOT.size != SLOT_HEAD_SIZE:  # pragma: no cover — 格式串写错即当场拦下
    raise AssertionError(f"槽头格式串与 {SLOT_HEAD_SIZE} 字节不符: {_SLOT.size}")

_KIND_NAMES = {ATTR_SLOT: "属性槽", BODY_SLOT: "正文槽"}


def offset_of(slot: int, *, slot_bytes: int) -> int:
    """某一格在载体文件里的字节地址:``文件头长度 + 槽号 × 格长``.

    **格号到地址是常数时间**:给一个槽号,地址当场算出;不查表,不扫目录,不读别的槽.

    Raises:
        SlotError: 槽号或格长为负.
    """
    if slot_bytes <= 0:
        raise SlotError(f"格长必须是正数: {slot_bytes}")
    if slot < 0:
        raise SlotError(f"槽号不能为负: {slot}")
    return HEADER_SIZE + slot * slot_bytes


class Slot(NamedTuple):
    """从载体里读出的一格:**它的种类与内容**.

    槽头只描述本格,故内容之外没有第二样事实——归属,片号,世代号都不在载体上.
    """

    kind: int
    """槽种类：属性槽或正文槽。"""

    content: bytes
    """内容本身；长度即槽头记的那个数。"""

    @property
    def kind_name(self) -> str:
        """槽种类的名字(诊断用)."""
        return _KIND_NAMES.get(self.kind, f"未知槽种类({self.kind})")


class Layout(NamedTuple):
    """载体的几何:文件头长度与格长,两项都从**文件头**读出."""

    head: int
    """文件头长度（字节）。"""

    slot: int
    """格长（字节）。**读取一律以此为准**——配置只决定新建载体时写什么。"""


def _read_header(path: Path) -> tuple[bytes, int, int]:
    """读并校验一个已有载体的文件头,返回(魔数,格长,文件长度).

    **格长只在这里从盘上读**:它是格式事实,写的时候定,读的时候从文件头读回来,
    故改一次配置不会让已落盘的载体错位.

    Raises:
        HubShapeError: 文件不在,文件头不完整,魔数不符,或格长不合法.
    """
    if not path.is_file():
        raise HubShapeError(f"载体不在: {path}")
    raw = path.read_bytes()[:HEADER_SIZE]
    if len(raw) < HEADER_SIZE:
        raise HubShapeError(f"载体文件头不完整: {path}（读到 {len(raw)} 字节）")
    magic, slot, _reserved = _HEADER.unpack(raw)
    if magic != MAGIC:
        raise HubShapeError(f"这不是本格式的载体: {path}（魔数 {magic!r}）")
    if slot <= 0:
        raise HubShapeError(f"载体文件头里的格长不合法: {slot}")
    return magic, int(slot), path.stat().st_size


def _pack_slot(kind: int, content: bytes, *, slot_bytes: int) -> bytes:
    """把一格编成字节:槽头 + 内容 + 补零,使下一格重新落在格边界上.

    Raises:
        SlotTooLargeError: 内容超过"格长减槽头".
    """
    room = slot_bytes - SLOT_HEAD_SIZE
    if len(content) > room:
        raise SlotTooLargeError(f"一格装不下 {len(content)} 字节（格长 {slot_bytes}，可用 {room}）")
    head = _SLOT.pack(kind, crc32(content) & 0xFFFFFFFF, len(content), b"\x00" * 7)
    return head + content + b"\x00" * (room - len(content))


class Pack:
    """一个载体文件:管格,管追加写,管原地覆盖,管顺扫;**它是槽的唯一可变面**.

    它不知道自己装的是属性还是正文:那是上一层的事.它只管"哪个槽是什么种类,装了什么".

    Args:
        path: 载体文件路径.
        slot_bytes: 新建时写进文件头的格长;**读取时不看它**.
        max_bytes: 封口线;写满即换新载体.
    """

    def __init__(
        self,
        path: Path,
        *,
        slot_bytes: int,
        max_bytes: int = DEFAULT_MAX_BYTES,
        size: int = HEADER_SIZE,
    ) -> None:
        """装配一个载体对象.**新建**走它写文件头;**打开**走 :meth:`open`.

        Args:
            path: 载体文件路径.
            slot_bytes: 格长(字节).新建时写进文件头;打开时由 :meth:`open` 从文件头读出.
            max_bytes: 封口线.
            size: 当前文件长度;默认即刚写完文件头的那一刻.

        Raises:
            SlotError: 格长不是正数.
            SlotTooLargeError: 格长装不下槽头.
        """
        if slot_bytes <= SLOT_HEAD_SIZE:
            raise SlotError(f"格长必须大于槽头（{SLOT_HEAD_SIZE} 字节）: {slot_bytes}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if size == HEADER_SIZE:
            path.write_bytes(_HEADER.pack(MAGIC, slot_bytes, 0))
        self._path = path
        self._max_bytes = max_bytes
        self._slot = slot_bytes
        self._size = size
        self._closed = False

    @classmethod
    def open(cls, path: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> Pack:
        """打开一个已有的载体:格长从**文件头**读,不看配置.

        Raises:
            HubShapeError: 文件不在,或魔数与格式常量不符(不推断,不当作"这里没有载体").
        """
        _magic, slot, size = _read_header(path)
        return cls(path, slot_bytes=slot, max_bytes=max_bytes, size=size)

    # ---- 属性 ---- #

    @property
    def path(self) -> Path:
        """载体文件路径."""
        return self._path

    @property
    def name(self) -> str:
        """载体名:**它就是文件的名字**,也是身份里 `in_hub_pack` 那一项."""
        return self._path.name

    @property
    def max_bytes(self) -> int:
        """封口线(字节)."""
        return self._max_bytes

    @property
    def size(self) -> int:
        """当前文件长度(字节),即**唯一那个可变事实**."""
        return self._size

    @property
    def slot_bytes(self) -> int:
        """格长(字节).读取一律以文件头里那一个为准."""
        return self._slot

    @property
    def slot_count(self) -> int:
        """已写过的格数:槽号 < 它即"写过",≥ 即"空闲"."""
        return (self._size - HEADER_SIZE) // self._slot

    @property
    def content_bytes(self) -> int:
        """一格能装的内容上限:格长减槽头."""
        return self._slot - SLOT_HEAD_SIZE

    @property
    def content_room(self) -> int:
        """一格能装的内容上限:**格长减槽头**."""
        return self._slot - SLOT_HEAD_SIZE

    def layout(self) -> Layout:
        """文件头长度与格长:读侧的一切算术都用它."""
        return Layout(head=HEADER_SIZE, slot=self._slot)

    @property
    def sealed(self) -> bool:
        """是否该换新载体.**它是策略判断,不是落盘状态**:改封口线即随之变.

        判据是"**剩下的地方装不下下一格**",而不是"长度达到了封口线":
        一个槽占一格,故还剩格子就不该封——否则那一格白扔.
        """
        return self._size + self._slot > self._max_bytes

    # ---- 读 ---- #

    def offset_of(self, slot: int) -> int:
        """某一格的字节地址:``文件头长度 + 槽号 × 格长``."""
        return offset_of(slot, slot_bytes=self._slot)

    def read(self, slot: int) -> Slot:
        """读出某一格:**校验并交出槽种类与内容**.

        **校验和不符即报错**:不把错的内容当成对的返回.没写过的格读出 `EMPTY_SLOT`
        与空内容,不算错——那是"这一格还空着".

        Raises:
            SlotError: 槽号越出文件尾.
            SlotFormatError: 槽头读不满,内容长度越出格长,或校验和不符.
            HubShapeError: 文件读不出来.
        """
        offset = self.offset_of(slot)
        if offset + self._slot > self._size:
            raise SlotError(
                f"槽号越界: {slot} 要到 {offset + self._slot} 字节，文件只有 {self._size}"
            )
        try:
            with self._path.open("rb") as handle:
                handle.seek(offset)
                raw = handle.read(self._slot)
        except OSError as error:
            raise HubShapeError(f"载体读不出来: {self._path}（{error}）") from error
        if len(raw) < SLOT_HEAD_SIZE:
            raise SlotFormatError(f"槽头读不满: 第 {slot} 格只读到 {len(raw)} 字节")
        kind, checksum, length, _reserved = _SLOT.unpack(raw[:SLOT_HEAD_SIZE])
        if length > self.content_bytes:
            raise SlotFormatError(
                f"内容长度越出格长: 第 {slot} 格声明 {length} 字节，"
                f"一格最多 {self.content_bytes} 字节"
            )
        content = raw[SLOT_HEAD_SIZE : SLOT_HEAD_SIZE + length]
        if kind != EMPTY_SLOT and (crc32(content) & 0xFFFFFFFF) != checksum:
            raise SlotFormatError(f"槽校验和不符: 第 {slot} 格的字节与它自己声明的不一致")
        return Slot(kind=kind, content=content)

    def scan(self) -> Iterator[tuple[int, Slot]]:
        """顺扫全部已写过的格:交出(槽号,槽).

        它**只服务诊断与回收**:读侧的一切定位都走索引库那一行给出的段列表.
        尾部若不是整格,或哪一格读不出来,即报错——那是残写或外来改动,不推断.
        """
        for slot in range(self.slot_count):
            yield slot, self.read(slot)

    def content_at(self, slot: int) -> bytes:
        """只取某一格的内容(跳过槽头);种类不是本层关心的事."""
        return self.read(slot).content

    # ---- 写 ---- #

    def append(self, kind: int, content: bytes) -> int:
        """把一个槽追加到载体末尾,返回它的槽号.

        **写到满才换**:本方法不判封口线,换不换文件由调用方按 :attr:`sealed` 决定.

        Raises:
            SlotTooLargeError: 内容超过一格能装的字节数.
            SlotFormatError: 文件尾不是整格(残写或外来改动,不推断续写起点).
            HubShapeError: 文件写不进去.
        """
        return self.write_at(self.slot_count, kind, content)

    def overwrite(self, slot: int, kind: int, content: bytes) -> None:
        """把一个槽**原地覆盖**:写在同一格号上,位置不变.

        属性槽走这一条;正文槽只追加,不覆盖.

        Raises:
            SlotError: 槽号不是已写过的格.
            SlotTooLargeError: 内容超过一格能装的字节数.
            HubShapeError: 文件写不进去.
        """
        if slot < 0 or slot >= self.slot_count:
            raise SlotError(f"只能覆盖已写过的格: 第 {slot} 格（已写到第 {self.slot_count} 格）")
        self.write_at(slot, kind, content)

    def write_at(self, slot: int, kind: int, content: bytes) -> int:
        """把一个槽写在指定的格号上:**槽号由调用方给定**,这正是"地址是算术"的用法.

        写到当前文件尾之后即补零拉长(回收按算好的位置落活槽靠它);写在文件尾之内
        即原地覆盖,位置不变.两种情形都不改动别格.

        Args:
            slot: 目标格号.
            kind: 槽种类.
            content: 内容.

        Returns:
            写下去的格号.

        Raises:
            SlotError: 格号为负.
            SlotTooLargeError: 内容超过一格能装的字节数.
            SlotFormatError: 文件尾不是整格(残写或外来改动,不推断续写起点).
            HubShapeError: 文件写不进去.
        """
        if self._closed:
            raise HubShapeError(f"载体已关闭: {self._path}")
        if slot < 0:
            raise SlotError(f"槽号不能为负: {slot}")
        body = self._size - HEADER_SIZE
        if body < 0 or body % self._slot:
            raise SlotFormatError(
                f"文件尾不是整格，拒绝续写: {self._path}（正文 {body} 字节，格长 {self._slot}）"
            )
        raw = _pack_slot(kind, content, slot_bytes=self._slot)
        try:
            with self._path.open("r+b") as handle:
                handle.seek(self.offset_of(slot))
                handle.write(raw)
                handle.flush()
        except OSError as error:
            raise HubShapeError(f"载体写不进去: {self._path}（{error}）") from error
        self._size = max(self._size, self.offset_of(slot) + self._slot)
        return slot

    def close(self) -> None:
        """标记本载体不再写.**不落任何标记**:文件本身就是全部事实."""
        self._closed = True

    def __repr__(self) -> str:
        """诊断用:名字,格长与当前长度,不读盘也不解析."""
        return f"Pack(name={self.name!r}, slot={self._slot}, size={self._size})"


__all__ = [
    "ATTR_SLOT",
    "BODY_SLOT",
    "DEFAULT_MAX_BYTES",
    "EMPTY_SLOT",
    "HEADER_SIZE",
    "MAGIC",
    "SLOT_HEAD_SIZE",
    "Layout",
    "Pack",
    "Slot",
    "offset_of",
]
