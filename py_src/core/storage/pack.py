# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""载体：一个文件，内含格；**一条记录占一或多格**，位置即头格与末格两个整数。

一句话就说得完：**文件里是格，块存在文件里，一个块可以跨多个格。**

本模块管三件事，多一件都不揽：

- **文件头**（24 字节）：魔数与格长。故**载体自描述**——只凭这个文件就能算偏移，
  不必问配置。格长随载体走：不同批次可以不同格长，各自照样精确算术定位；
- **记录**：自带总长、校验和**与它自己的身份**，故顺扫即可切出全部记录并知道各自是谁，
  **不依赖索引库**。这是"库丢了能重建"的前提；
- **追加写**：写到文件尾，写完补齐格尾。**唯一可变的事实是文件尾在哪**——
  没有空闲表、没有分配位图：格号 < 文件尾格数即"写过"，≥ 即"空闲"。

**记录头里的身份就是 ID 的落盘部分**（两套凭证、名字、签发时刻）：身份必须在记录里，
否则索引库一丢，"这一格是谁"就无从复原。位置段不在其中——扫到它时位置已经由扫描给出了。

**封口是策略，不是状态**：写满封口线就换新载体，但文件里不留任何封印标记——
"已封口"就是"这个载体达到了封口线"。故改封口线不会出现"标记与事实不符"。

**读路径不建东西**：文件不在即报错，不新建一个空的顶上——空载体与"载体丢了"必须分得开。
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, NamedTuple
from zlib import crc32

import cbor2

from core.exc import HubShapeError, RecordFormatError, SlotError

from .db.id import ID
from .slot import Slot, SlotRange, offset_of, span_of

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

MAGIC = b"CairnPk1"
"""载体魔数：末位是布局版本号。不符即报错，不作推断，也不当作"此处没有载体"。"""

HEADER_SIZE = 24
"""文件头长度（字节）：魔数 8 ＋ 格长 8 ＋ 预留 8。**它不必凑成整格**。"""

RECORD_HEAD_SIZE = 16
"""记录头的定长部分（字节）：总长 4 ＋ 校验和 4 ＋ 身份段长度 4 ＋ 预留 4。

三项都定长于格边界之前，故记录起点永远落在格边界上，且**单格记录也不浪费一格**。
身份段（canonical CBOR）跟在定长部分之后，长度自报。
"""

DEFAULT_MAX_BYTES = 2 * 1024**3
"""封口线：单个载体写满这个字节数就换新载体。只管"换不换文件"，不是硬上限。"""

_HEADER = struct.Struct(">8sQQ")
_RECORD = struct.Struct(">III4x")

_MIN_TOTAL = RECORD_HEAD_SIZE
"""一条记录的最小总长：有头、身份为空、载荷为空。"""


class Record(NamedTuple):
    """从载体里读出的一条记录：**它是谁、躺在哪个载体的哪几格、装了什么**。

    Attributes:
        identity: 记录里的 ID（两套凭证、名字、签发时刻）。位置段它是空的——
            位置由 `owner` 与 `span` 给出，它是投影。
        owner: 它所在的**载体名**。记录自己不带位置，故"在哪个文件"由读它的那一方补上。
        span: 占的格区间（头格，末格），闭区间。
        payload: 记录内容。
    """

    identity: ID
    owner: str
    span: SlotRange
    payload: bytes

    @property
    def located(self) -> bool:
        """位置是否齐全（载体名与格区间都有）。"""
        return bool(self.owner)


def frame(identity: ID, payload: bytes) -> bytes:
    """把一条记录框起来：**总长 + 校验和 + 身份段长度 + 身份 + 载荷**。

    自框定是必须的：没有它，一条记录的位置就得靠外部索引才切得出来，于是"库丢了能重建"
    这条不成立。校验和验的是"读到的是不是原文"——**它不承担内容寻址**：内容凭证走 ID 的
    摘要形态，两件事不该由一处兼职。

    Args:
        identity: 这条记录的身份（ID 的落盘部分进记录头）。
        payload: 记录内容。

    Returns:
        可整段写进载体的字节。
    """
    segment = cbor2.dumps(identity.to_record(), canonical=True)
    total = RECORD_HEAD_SIZE + len(segment) + len(payload)
    head = _RECORD.pack(total, crc32(payload), len(segment))
    return head + segment + payload


def unframe(raw: bytes, *, slot: int) -> tuple[ID, int, bytes]:
    """把一段"从记录头开始"的字节解开成（身份，总长，载荷）。

    Raises:
        RecordFormatError: 记录头不完整、总长或身份段越界、格长对不上，或校验和不符。
    """
    if len(raw) < RECORD_HEAD_SIZE:
        raise RecordFormatError(f"记录头不完整：读到 {len(raw)} 字节，至少要 {RECORD_HEAD_SIZE}")
    total, checksum, id_len = _RECORD.unpack_from(raw, 0)
    if total < RECORD_HEAD_SIZE:
        raise RecordFormatError(f"记录总长不合法: {total}")
    if total > len(raw):
        raise RecordFormatError(f"记录被截断：声明 {total} 字节，只读到 {len(raw)}")
    if id_len <= 0 or RECORD_HEAD_SIZE + id_len > total:
        raise RecordFormatError(f"身份段长度不合法: {id_len}（记录总长 {total}）")
    span = span_of(total, slot=slot)
    if span.size * slot > len(raw):
        raise RecordFormatError(f"记录越出载体尾部：声明 {total} 字节，落在第 {span.last} 格之外")
    segment = raw[RECORD_HEAD_SIZE : RECORD_HEAD_SIZE + id_len]
    payload = raw[RECORD_HEAD_SIZE + id_len : total]
    if crc32(payload) != checksum:
        raise RecordFormatError("记录校验和不符：这一段的字节与它自己声明的不一致")
    try:
        decoded = cbor2.loads(segment)
    except cbor2.CBORDecodeError as error:
        raise RecordFormatError(f"记录里的身份段解不出来: {error}") from error
    if not isinstance(decoded, dict):
        raise RecordFormatError("记录里的身份段不是映射")
    try:
        identity = ID.from_record(decoded)
    except (TypeError, ValueError) as error:
        raise RecordFormatError(f"记录里的身份不合法: {error}") from error
    return identity, total, payload


def _read_header(path: Path) -> tuple[bytes, int, int]:
    """读并校验一个已有载体的文件头，返回（魔数，格长，文件长度）。

    **格长只在这里从盘上读**：它是格式事实，写的时候定、读的时候从文件头读回来，
    故改一次配置不会让已落盘的载体错位。

    Raises:
        HubShapeError: 文件不在、文件头不完整、魔数不符，或格长不合法。
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


class Layout(NamedTuple):
    """载体的几何：文件头长度与格长，两项都从**文件头**读出。"""

    head: int
    """文件头长度（字节）。"""

    slot: int
    """格长（字节）。**读取一律以此为准**——配置只决定新建载体时写什么。"""


class Pack:
    """一个载体文件：管格、管追加写、管顺扫；**它是格的唯一可变面**。

    它不知道自己装的是块还是内容：那是上一层的事。它只管"谁（ID）在哪几格、装了什么"。

    Args:
        path: 载体文件路径。
        slot_bytes: 新建时写进文件头的格长；**读取时不看它**。
        max_bytes: 封口线；写满即换新载体。
    """

    def __init__(
        self,
        path: Path,
        *,
        slot_bytes: int,
        max_bytes: int = DEFAULT_MAX_BYTES,
        size: int = HEADER_SIZE,
    ) -> None:
        """装配一个载体对象。**新建**走它写文件头；**打开**走 :meth:`open`。

        Args:
            path: 载体文件路径。
            slot_bytes: 格长（字节）。新建时写进文件头；打开时由 :meth:`open` 从文件头读出。
            max_bytes: 封口线。
            size: 当前文件长度；默认即刚写完文件头的那一刻。
        """
        if slot_bytes <= 0:
            raise SlotError(f"格长必须是正数: {slot_bytes}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if size == HEADER_SIZE:
            path.write_bytes(_HEADER.pack(MAGIC, slot_bytes, 0))
        self._path = path
        self._max_bytes = max_bytes
        self._head = HEADER_SIZE
        self._slot = slot_bytes
        self._size = size
        self._closed = False

    @classmethod
    def open(cls, path: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> Pack:
        """打开一个已有的载体：格长从**文件头**读，不看配置。

        Raises:
            HubShapeError: 文件不在，或魔数与格式常量不符（不推断、不当作"这里没有载体"）。
        """
        _magic, slot, size = _read_header(path)
        return cls(path, slot_bytes=slot, max_bytes=max_bytes, size=size)

    # ---- 属性 ---- #

    @property
    def path(self) -> Path:
        """载体文件路径。"""
        return self._path

    @property
    def name(self) -> str:
        """载体名：**它就是文件的名字**，也是 ID 的 `in_hub_pack` 那一项。"""
        return self._path.name

    @property
    def max_bytes(self) -> int:
        """封口线（字节）。"""
        return self._max_bytes

    @property
    def size(self) -> int:
        """当前文件长度（字节），即**唯一那个可变事实**。"""
        return self._size

    def layout(self) -> Layout:
        """文件头长度与格长：读侧的一切算术都用它。"""
        return Layout(head=self._head, slot=self._slot)

    @property
    def sealed(self) -> bool:
        """是否该换新载体。**它是策略判断，不是落盘状态**：改封口线即随之变。

        判据是"**剩下的地方装不下下一格**"，而不是"长度达到了封口线"：一条记录至少占一格，
        故还剩格子就不该封——否则那一格白扔，而写入纪律本该是"写到满才换"。

        单条记录大于封口线时不必担心：:meth:`append` 不判封口线，整条照写。
        """
        return self._size + self._slot > self._max_bytes

    # ---- 读 ---- #

    def offset_of(self, first: int) -> int:
        """某一格在文件里的字节偏移：``文件头长度 + 格号 × 格长``。"""
        return offset_of(first, head=self._head, slot=self._slot)

    def read_span(self, span: SlotRange) -> bytes:
        """读出某几格的全部字节（**含记录头与格尾补零**）。

        要直接拿到记录走 :meth:`read`，要载荷走 :meth:`read_payload`。

        Raises:
            SlotError: 格区间越界（它落在文件尾之后）。
            HubShapeError: 文件读不出来。
        """
        offset = self.offset_of(span.first)
        length = span.size * self._slot
        if offset + length > self._size:
            raise SlotError(
                f"格区间越界: {span.first}..{span.last} 要到 {offset + length} 字节，"
                f"文件只有 {self._size}"
            )
        try:
            with self._path.open("rb") as handle:
                handle.seek(offset)
                return handle.read(length)
        except OSError as error:
            raise HubShapeError(f"载体读不出来: {self._path}（{error}）") from error

    def read(self, span: SlotRange) -> Record:
        """按格区间读出**一条记录**（身份、格区间、载荷）。

        Raises:
            RecordFormatError: 记录头、身份段或校验和对不上。
        """
        identity, _total, payload = unframe(self.read_span(span), slot=self._slot)
        return Record(identity=identity, owner=self.name, span=span, payload=payload)

    def read_payload(self, span: SlotRange) -> bytes:
        """按格区间只读出**载荷**（跳过记录头与身份段）。"""
        _identity, _total, payload = unframe(self.read_span(span), slot=self._slot)
        return payload

    def slot(self, first: int, last: int) -> Slot:
        """取某一段格的只读视图。**它不读盘**：真正读是 :meth:`Slot.read`。"""
        return Slot(self, SlotRange(first, last))

    def scan(self) -> Iterator[Record]:
        """顺扫全部记录：交出 :class:`Record`，**不依赖索引库**。

        记录自框定（总长在最前），故一遍扫完即得全部记录——这是重建与巡检的取数口。
        尾部若不足一整格，或哪条记录读不到底，即报错：那是残写或外来改动，
        **不推断续写起点**。

        Raises:
            RecordFormatError: 尾部残留不足一整格，或某条记录的头、身份、校验和对不上。
            HubShapeError: 文件读不出来。
        """
        try:
            raw = self._path.read_bytes()
        except OSError as error:
            raise HubShapeError(f"载体读不出来: {self._path}（{error}）") from error
        body = raw[self._head :]
        if len(body) % self._slot:
            raise RecordFormatError(
                f"载体尾部不是整格: {self._path}（正文 {len(body)} 字节，格长 {self._slot}）"
            )
        cursor = 0
        while cursor < len(body):
            rest = body[cursor:]
            identity, total, payload = unframe(rest, slot=self._slot)
            span = span_of(total, slot=self._slot)
            occupied = span.size * self._slot
            if occupied > len(rest):
                raise RecordFormatError(f"记录越出载体尾部: {cursor} 起声明占 {occupied} 字节")
            first = cursor // self._slot
            yield Record(
                identity=identity,
                owner=self.name,
                span=SlotRange(first, first + span.size - 1),
                payload=payload,
            )
            cursor += occupied

    # ---- 写 ---- #

    def append(self, identity: ID, payload: bytes) -> SlotRange:
        """把一条记录追加到载体末尾，返回它占的格区间。

        **写到满才换**：本方法不判封口线，换不换文件由调用方按 :attr:`sealed` 决定——
        否则"单条记录大于封口线"就永远写不进去。

        Args:
            identity: 这条记录的身份；它的落盘部分进记录头。
            payload: 记录内容。

        Raises:
            RecordFormatError: 文件尾不是整格（残写或外来改动，不推断续写起点）。
            HubShapeError: 文件写不进去。
        """
        if self._closed:
            raise HubShapeError(f"载体已关闭: {self._path}")
        body = self._size - self._head
        if body < 0 or body % self._slot:
            raise RecordFormatError(
                f"文件尾不是整格，拒绝续写: {self._path}（正文 {body} 字节，格长 {self._slot}）"
            )
        raw = frame(identity, payload)
        span = span_of(len(raw), slot=self._slot)
        padded = raw + b"\x00" * (span.size * self._slot - len(raw))
        try:
            with self._path.open("ab") as handle:
                handle.write(padded)
                handle.flush()
        except OSError as error:
            raise HubShapeError(f"载体写不进去: {self._path}（{error}）") from error
        self._size += len(padded)
        first = body // self._slot
        return SlotRange(first, first + span.size - 1)

    def close(self) -> None:
        """标记本载体不再写。**不落任何标记**：文件本身就是全部事实。"""
        self._closed = True

    def __repr__(self) -> str:
        """诊断用：名字、格长与当前长度，不读盘也不解析。"""
        return f"Pack(name={self.name!r}, slot={self._slot}, size={self._size})"


__all__ = [
    "DEFAULT_MAX_BYTES",
    "HEADER_SIZE",
    "MAGIC",
    "RECORD_HEAD_SIZE",
    "Layout",
    "Pack",
    "Record",
    "frame",
    "unframe",
]
