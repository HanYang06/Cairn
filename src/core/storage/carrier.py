# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""载体文件：定长格的追加写文件（含格算术与文件头）。

模型只有一条：**载体是一串等大的格子，记录从格边界开始写，写不下就往后拼格子**。
一条记录的位置就是它占的**头一格与末一格**这两个数字。由此得到三件确定的事：

- **定位是乘法**：字节偏移 ＝ 文件头长度 ＋ 起始格 × 槽长；没有第二套口径，
  也不需要解释"槽数"的两种含义（格号自文件头之后起算，故文件头不必凑成整格）；
- **载体自描述**：槽长写进文件头，只拿到一个文件也能算偏移（设计篇 §5.5）；
- **尾部永远是整格**：写完一条记录，末格空着的部分补零——下一格一定落在格边界上，
  故"记录从格边界开始"是这条模型的硬约束，不是约定俗成。

代价只有一个，且是明确的：**一条记录至少占一格，格尾写不满就空着**。所以槽长是
"空间浪费"与"格号数量"之间的交换——格小则每条浪费小、格号多；格大则相反。
本层对此不做取舍，槽长由上层在建载体时给出。

封口是策略判断，不是落盘状态（§5.4）：本层只回答"写满没有"，换不换文件由上层决定。
读取时若发现文件尾部不是整格，一律报错——那是残写或外来文件，不是我们要猜的东西。
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Self

from core.exc import RecordFormatError, SlotError

from .format.record import HEADER_BYTES as RECORD_HEADER_BYTES
from .format.record import LEN_BYTES

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType

MAGIC = b"CAIRNPK1"
"""魔数：末位是布局版本 1。不符即报错，不猜。"""

_SLOT_FIELD_BYTES = 8
_RESERVED_BYTES = 8

HEADER_BYTES = len(MAGIC) + _SLOT_FIELD_BYTES + _RESERVED_BYTES
"""载体文件头长度：魔数 8 ＋ 槽长 8 ＋ 预留 8 ＝ 24 字节。"""


def build_header(slot_bytes: int) -> bytes:
    """生成载体文件头：魔数 ＋ 槽长（大端无符号）＋ 预留置零。"""
    return (
        MAGIC
        + _check_slot_bytes(slot_bytes).to_bytes(_SLOT_FIELD_BYTES, "big")
        + bytes(_RESERVED_BYTES)
    )


def parse_header(raw: bytes) -> int:
    """校验并解析载体文件头，返回槽长。

    只认魔数与槽长：预留段留给将来的布局增量，不校验内容（校验了反而挡住向前兼容）。

    Raises:
        RecordFormatError: 文件头不足，或魔数不符（不是载体，或不是第 1 版布局）。
        SlotError: 文件头里的槽长不合法。
    """
    if len(raw) < HEADER_BYTES:
        raise RecordFormatError(f"载体文件头不足: {len(raw)} < {HEADER_BYTES}")
    if not raw.startswith(MAGIC):
        raise RecordFormatError("不是载体文件，或不是第 1 版布局")
    slot_start = len(MAGIC)
    slot_bytes = int.from_bytes(raw[slot_start : slot_start + _SLOT_FIELD_BYTES], "big")
    return _check_slot_bytes(slot_bytes)


def slots_needed(total_len: int, slot_bytes: int) -> int:
    """装下这么多字节需要几个格（至少一个格）。

    这是本层唯一的格算术：装不下就往后拼格子，末格写不满照样算一个格。
    """
    length = _check_positive(total_len, "记录长度")
    return max(1, -(-length // _check_slot_bytes(slot_bytes)))


@dataclass(frozen=True, slots=True)
class SlotRange:
    """载体内的格区间：**物理坐标**，闭区间 ``[first, last]``。

    两个数字即精确位置：记录从 ``first`` 格的格边界开始，占用到 ``last`` 格。
    ``last`` 可由记录头声明的总长推出，写下来是为了**自检与可读**——读到记录时核对
    "声明的末格"与"总长推出的末格"是否一致，不一致即这份坐标与载体对不上
    （索引被改坏、载体被替换），当场报错而不是读出一段错位内容。

    物理坐标是投影而非事实（§5.2）：压缩、合并与搬移只改这份映射，不改记录携带的任何内容。

    Attributes:
        first: 起始格号。
        last: 末格号（闭区间上界），不小于 ``first``。
    """

    first: int
    last: int

    def __post_init__(self) -> None:
        """校验：起始格非负，末格不小于起始格。"""
        if self.first < 0:
            raise SlotError(f"起始格不能为负: {self.first}")
        if self.last < self.first:
            raise SlotError(f"末格不能小于起始格: {self.first}-{self.last}")

    @property
    def count(self) -> int:
        """占用格数：由两个数字推出，不单独存。"""
        return self.last - self.first + 1

    def offset(self, slot_bytes: int) -> int:
        """字节偏移：文件头长度 ＋ 起始格 × 槽长（格模型下就是加法与乘法）。"""
        return HEADER_BYTES + self.first * _check_slot_bytes(slot_bytes)

    def __str__(self) -> str:
        """紧凑写法 ``头格-末格``；调试与日志用，不是落盘格式。"""
        return f"{self.first}-{self.last}"


class Carrier:
    """一个载体文件：定长格、追加写、按格区间读、顺扫。

    打开既有文件时**槽长一律以文件头为准**；新建时必须给出槽长。文件句柄在实例生命周期内
    保持打开，作上下文管理器可确保关闭。本层不做并发保护，也不管封口换不换文件。
    """

    def __init__(self, path: str | Path, *, slot_bytes: int | None = None) -> None:
        """打开或新建载体。

        Args:
            path: 载体文件路径；父目录须已存在（建目录是桶的职责）。
            slot_bytes: 槽长。新建时必需；打开既有文件时若给了，必须与文件头一致。

        Raises:
            SlotError: 新建却没给槽长，或给的槽长与文件头不符。
            RecordFormatError: 文件头不足或魔数不符。
        """
        self._path = Path(path)
        if self._path.exists():
            handle = self._path.open("r+b")
            try:
                self._slot_bytes = parse_header(handle.read(HEADER_BYTES))
            except (RecordFormatError, SlotError):
                handle.close()
                raise
            if slot_bytes is not None and _check_slot_bytes(slot_bytes) != self._slot_bytes:
                handle.close()
                raise SlotError(
                    f"槽长与载体文件头不符: 给定 {slot_bytes}，文件头 {self._slot_bytes}"
                )
            self._file = handle
        else:
            if slot_bytes is None:
                raise SlotError("新建载体必须给出槽长")
            self._slot_bytes = _check_slot_bytes(slot_bytes)
            handle = self._path.open("w+b")
            handle.write(build_header(self._slot_bytes))
            handle.flush()
            self._file = handle

    @property
    def path(self) -> Path:
        """载体文件路径。"""
        return self._path

    @property
    def slot_bytes(self) -> int:
        """本载体的槽长（来自文件头，不是配置）。"""
        return self._slot_bytes

    @property
    def size(self) -> int:
        """当前文件字节数；格模型下"文件头之后的记录区"恒是槽长的整数倍。"""
        self._file.seek(0, io.SEEK_END)
        return self._file.tell()

    def sealed(self, max_bytes: int) -> bool:
        """是否已达封口线；封口线只管"换不换文件"，不构成写入的硬上限（§5.4）。"""
        return self.size >= max_bytes

    def append(self, raw: bytes) -> SlotRange:
        """把一条记录追加到载体末尾，返回它占的格区间。

        写入前核对两件事：记录的自框定字段（总长必须等于这批字节的实际长度），以及**尾部在格边界上**
        （否则这条记录就不是从格边界开始的，两数定位立刻失效）。写完后把末格补齐，
        使下一格重新落在格边界。**不检查封口线**——单条记录大于封口线时照样完整写入（§5.4）。

        Raises:
            RecordFormatError: 记录短于记录头、总长与实际字节数不符，或载体尾部不在格边界。
        """
        _check_self_framed(raw)
        size = self.size
        body = size - HEADER_BYTES
        if body % self._slot_bytes:
            raise RecordFormatError(
                f"载体尾部不在格边界: 记录区长度 {body} 不是槽长 {self._slot_bytes} 的整数倍"
            )
        first = body // self._slot_bytes
        self._file.seek(size)
        self._file.write(raw)
        padding = -len(raw) % self._slot_bytes
        if padding:
            self._file.write(bytes(padding))
        self._file.flush()
        return SlotRange(first=first, last=first + slots_needed(len(raw), self._slot_bytes) - 1)

    def read(self, span: SlotRange) -> bytes:
        """按格区间读出一条记录的原始字节（不做解码，解码是记录层的事）。

        读之前核对"区间声明的末格"与"记录头声明的总长推出的末格"：两者不符说明这份坐标已经和
        载体对不上，当场抛错。

        Raises:
            SlotError: 末格与记录长度推出的不一致。
            RecordFormatError: 偏移处读不到记录头，或记录被截断。
        """
        offset = span.offset(self._slot_bytes)
        total_len = self._read_total_len(offset)
        expected_last = span.first + slots_needed(total_len, self._slot_bytes) - 1
        if expected_last != span.last:
            raise SlotError(f"末格与记录长度不符: 区间声明到 {span.last}，记录推出 {expected_last}")
        raw = self._read_at(offset, total_len)
        if len(raw) != total_len:
            raise RecordFormatError(
                f"记录被截断: 偏移 {offset} 需要 {total_len} 字节，只读到 {len(raw)}"
            )
        return raw

    def scan(self) -> Iterator[tuple[SlotRange, bytes]]:
        """从头顺扫全部记录，交出 ``(格区间, 原始字节)``。

        记录自框定，故顺扫即可重建定位——这是"不设封口目录"的依据（§5.4）。每次前进一整格数，
        故末格里的补零字节不会被当成下一条记录。**坏点即停**：读不出总长或截断即抛错；
        "跳过坏点继续扫"是巡检的策略（§8.7），不是本层。

        Raises:
            RecordFormatError: 记录头读不出或记录被截断。
        """
        offset = HEADER_BYTES
        end = self.size
        while offset < end:
            total_len = self._read_total_len(offset)
            raw = self._read_at(offset, total_len)
            if len(raw) != total_len:
                raise RecordFormatError(
                    f"记录被截断: 偏移 {offset} 需要 {total_len} 字节，只读到 {len(raw)}"
                )
            count = slots_needed(total_len, self._slot_bytes)
            first = (offset - HEADER_BYTES) // self._slot_bytes
            yield SlotRange(first=first, last=first + count - 1), raw
            offset += count * self._slot_bytes

    def close(self) -> None:
        """关闭文件句柄；重复调用安全。"""
        self._file.close()

    def __enter__(self) -> Self:
        """进入 ``with``：载体可用。"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """退出 ``with``：无论是否异常都关闭句柄。"""
        self.close()

    def _read_total_len(self, offset: int) -> int:
        """读出偏移处的记录总长，并挡掉"总长小于记录头"这种会让顺扫打转的脏值。"""
        head = self._read_at(offset, LEN_BYTES)
        if len(head) < LEN_BYTES:
            raise RecordFormatError(f"偏移 {offset} 处读不到记录总长")
        total_len = int.from_bytes(head, "big")
        if total_len < RECORD_HEADER_BYTES:
            raise RecordFormatError(f"偏移 {offset} 处的记录总长非法: {total_len}")
        return total_len

    def _read_at(self, offset: int, count: int) -> bytes:
        """从偏移处读若干字节（不足即返回实际读到的，由调用方判断截断）。"""
        self._file.seek(offset)
        return self._file.read(count)


def _check_slot_bytes(slot_bytes: int) -> int:
    """槽长必须为正；这是格式事实，不是可调参数（§5.6）。"""
    if slot_bytes < 1:
        raise SlotError(f"槽长必须为正: {slot_bytes}")
    return slot_bytes


def _check_positive(value: int, what: str) -> int:
    """正数校验。"""
    if value < 1:
        raise SlotError(f"{what}必须为正: {value}")
    return value


def _check_self_framed(raw: bytes) -> None:
    """写入前核对自框定字段：总长必须等于这批字节的实际长度。"""
    if len(raw) < RECORD_HEADER_BYTES:
        raise RecordFormatError(f"记录短于记录头: {len(raw)} < {RECORD_HEADER_BYTES}")
    total_len = int.from_bytes(raw[:LEN_BYTES], "big")
    if total_len != len(raw):
        raise RecordFormatError(f"总长与实际字节数不符: 声明 {total_len}，实际 {len(raw)}")


__all__ = [
    "HEADER_BYTES",
    "MAGIC",
    "Carrier",
    "SlotRange",
    "build_header",
    "parse_header",
    "slots_needed",
]
