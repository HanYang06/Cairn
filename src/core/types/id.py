# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""身份：ID 与其两套凭证（分配形态与摘要形态）。

设计见 `docs/architecture/storage-design.md` §3。要点：

- **ID 是 body 的身份证**，不是裸字符串。它承载身份与位置，不承载物理坐标（§3.2.1、§9.2）；
- 本体为**两种凭证并存**：``value_uuid``（签发时分配，比较有效、去重无效）与
  ``value_hash``（由内容算出，比较无效、去重有效）。两者都能当 ID 用，互不替代（§3.2）；
- ``issued`` 是 **ID 自身**被签发的时间点，不等于块 / 对象 / 数据的创建时间（§3.2）；
- **落盘只取必需子集**，由 :meth:`Id.record` 给出；可推导字段（路径 / 文件名 / 网络）留在对象里
  供自描述与排查，不进库与载体（§3.3 第 6 条、§3.5）。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from blake3 import blake3

from .common import now_ms
from .errors import InvalidIdError

if TYPE_CHECKING:
    from collections.abc import Mapping

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_UUID_LEN = 26
_DIGEST_LEN = 64
_HEX_DIGITS = frozenset("0123456789abcdef")

_REQUIRED_RECORD_KEYS = ("value_uuid", "value_hash", "issued")
"""落盘子集里**不可缺**的键；其余按空值还原（见 `Id.from_record`）。"""


def _encode_crockford(value: int, length: int) -> str:
    """把整数编成定长 Crockford Base32（高位在前）。"""
    chars = [""] * length
    for index in range(length - 1, -1, -1):
        chars[index] = _CROCKFORD[value & 0x1F]
        value >>= 5
    return "".join(chars)


class ValueUuid(str):
    """分配形态凭证：26 字符 Crockford Base32（ULID 布局：48 位毫秒 + 80 位随机）。

    性质（§3.2）：比较**有效**；去重**无效**（每次签发都不同）。
    时间有序，故同批 ID 天然按签发顺序排列。
    """

    __slots__ = ()

    @classmethod
    def new(cls) -> ValueUuid:
        """签发一个新的凭证（当前毫秒 + 80 位随机）。"""
        stamp = now_ms() & ((1 << 48) - 1)
        random_bits = int.from_bytes(secrets.token_bytes(10), "big")
        return cls(_encode_crockford((stamp << 80) | random_bits, _UUID_LEN))

    @classmethod
    def parse(cls, value: str) -> ValueUuid:
        """按格式解析；首字符上限 ``7`` 是 ULID 规范的溢出保护。"""
        normalized = str(value).upper()
        if len(normalized) != _UUID_LEN or normalized[0] > "7":
            raise InvalidIdError(f"非法唯一标识凭证: {value!r}")
        for char in normalized:
            if char not in _CROCKFORD:
                raise InvalidIdError(f"非法唯一标识凭证: {value!r}")
        return cls(normalized)

    @property
    def time_ms(self) -> int:
        """凭证内嵌的时间戳（unix 毫秒，前 48 位）。"""
        value = 0
        for char in self:
            value = (value << 5) | _CROCKFORD.index(char)
        return value >> 80


class ValueHash(str):
    """摘要形态凭证：32 字节摘要的小写十六进制（64 字符）。

    性质（§3.2）：去重**有效**（同内容同值）；比较**无效**（同内容同值，不可比）。
    与内容寻址共用同一口径，故它同时是"是哪一份内容"的答案。
    """

    __slots__ = ()

    @classmethod
    def of(cls, data: bytes, *, context: bytes = b"") -> ValueHash:
        """按内容算摘要；``context`` 做域分隔（同一内容按用途取不同摘要）。"""
        hasher = blake3()
        if context:
            hasher.update(context)
        hasher.update(data)
        return cls(hasher.hexdigest())

    @classmethod
    def from_digest(cls, digest: bytes) -> ValueHash:
        """由 32 字节原始摘要构造。"""
        if len(digest) != 32:
            raise InvalidIdError(f"非法摘要长度: {len(digest)}（应为 32 字节）")
        return cls(digest.hex())

    @classmethod
    def parse(cls, value: str) -> ValueHash:
        """按格式解析（64 位小写十六进制）。"""
        normalized = str(value)
        if len(normalized) != _DIGEST_LEN or not set(normalized) <= _HEX_DIGITS:
            raise InvalidIdError(f"非法内容摘要凭证: {value!r}")
        return cls(normalized)


@dataclass(frozen=True, slots=True)
class SlotRange:
    """载体内的槽区间：物理坐标，**含槽内偏移**。

    三元组 ``(start, count, head)``：占 ``count`` 个槽，自第 ``start`` 个槽的
    ``head`` 字节处开始。

    为什么必须有 ``head``：记录只把**起点向下取整到槽边界**，其余紧接前一条连续写。
    若只记 ``(start, count)``，"第 2 条记录从第 4 槽开始"就无法与"第 1 条也从第 4 槽开始"
    区分——两段的起点会撞在同一个字节上，读第 2 条会读出第 1 条的头部。
    ``head`` 一旦带上，**字节偏移与槽区间互为逆运算**，索引里的位置也就无需另存偏移。

    属物理坐标，只在载体层与自描述内部流通（§5.1、§9.2）；**不进落盘子集**。
    区间可多段，故 ID 以元组持有。
    """

    start: int
    count: int
    head: int = 0

    def __post_init__(self) -> None:
        """校验：起始槽与槽内偏移非负、槽数为正。"""
        if self.start < 0:
            raise ValueError(f"槽区间起始值不能为负: {self.start}")
        if self.count < 1:
            raise ValueError(f"槽区间长度至少为 1: {self.count}")
        if self.head < 0:
            raise ValueError(f"槽内偏移不能为负: {self.head}")

    @property
    def end(self) -> int:
        """末槽（闭区间上界）——由起始与槽数推出，不单独存。"""
        return self.start + self.count - 1

    def __str__(self) -> str:
        """紧凑写法：``起始:槽数:槽内偏移``。"""
        return f"{self.start}:{self.count}:{self.head}"

    @classmethod
    def parse(cls, value: str) -> SlotRange:
        """解析 ``起始:槽数:槽内偏移``；省略第三段时槽内偏移取 0。

        它与 :meth:`__str__` 互逆，是槽区间的落盘 / 调试形态。

        **只认 ASCII 数字**：``str.isdecimal()`` 对全角数字（``１２``）与阿拉伯-印度数字
        （``١٢``）同样返回真、``int()`` 也照收，于是落盘形态会莫名其妙地"能解析"。
        这个格式是我们自己的调试 / 落盘写法，收紧到 ASCII 才不会让脏字节混进来。
        """
        parts = str(value).split(":")
        if len(parts) not in (2, 3) or not all(
            part.isascii() and part.isdecimal() for part in parts
        ):
            raise InvalidIdError(f"非法槽区间: {value!r}")
        start, count = int(parts[0]), int(parts[1])
        head = int(parts[2]) if len(parts) == 3 else 0
        try:
            return cls(start, count, head)
        except ValueError as exc:  # 槽数为 0 等情况由数据类校验拦下
            raise InvalidIdError(f"非法槽区间: {value!r}") from exc


@dataclass(frozen=True, slots=True)
class Id:
    """身份证：body 的身份与位置（§3）。

    两套凭证并存：``value_uuid`` 分配而来、``value_hash`` 由内容算出。
    位置字段可冗余（自描述与排查之用），落盘只取 :meth:`record` 给出的最小集。
    """

    # ---- 身份段 ----
    value_uuid: ValueUuid
    """分配形态凭证：比较有效、去重无效。"""

    value_hash: ValueHash
    """摘要形态凭证：去重有效、与内容寻址同源。"""

    name: str = ""
    """名字；由所在容器得出（body ID / block ID / note block ID …）。"""

    issued: int = field(default_factory=now_ms)
    """**ID 自身**被签发的时间点（unix 毫秒）；不等于块 / 对象 / 数据的创建时间。"""

    issuer: str = ""
    """签发者。"""

    # ---- 位置段（自描述；可推导者不落盘）----
    in_bucket_name: str = ""
    """在哪个桶。"""

    in_pack_name: str = ""
    """在哪个载体文件。"""

    in_pack_path: str = ""
    """载体所在路径（由桶目录与载体名推出，不落盘）。"""

    in_file_path: str = ""
    """文件路径（可分片跨载体，通常为空或单值）。"""

    in_file_name: str = ""
    """文件名称（可分片跨载体，通常为空或单值）。"""

    in_file_slot: tuple[SlotRange, ...] = ()
    """槽区间；可分多段。物理坐标，不落盘。"""

    # ---- 来源段（跨设备预留；当前不落盘）----
    in_net_ip: str = ""
    """在哪台机器（网络与联邦成稿时定义）。"""

    @classmethod
    def new(  # noqa: PLR0913 — 工厂参数对应各字段，拆包反而更绕
        cls,
        content: bytes,
        *,
        name: str = "",
        issuer: str = "",
        hash_context: bytes = b"",
        in_bucket_name: str = "",
        in_pack_name: str = "",
        in_pack_path: str = "",
        in_file_path: str = "",
        in_file_name: str = "",
        in_file_slot: tuple[SlotRange, ...] = (),
        in_net_ip: str = "",
    ) -> Id:
        """签发一个新 ID：两套凭证一次生成，位置字段按需传入。

        ``content`` 参与摘要形态的计算；分配形态与内容无关。
        位置段字段显式列出（不用 ``**kwargs``）：字段名写错在类型检查期即被拦下，
        而不是等到运行期被静默丢弃。可推导字段留空即可，落盘只取 :meth:`record`。
        """
        return cls(
            value_uuid=ValueUuid.new(),
            value_hash=ValueHash.of(content, context=hash_context),
            name=name,
            issued=now_ms(),
            issuer=issuer,
            in_bucket_name=in_bucket_name,
            in_pack_name=in_pack_name,
            in_pack_path=in_pack_path,
            in_file_path=in_file_path,
            in_file_name=in_file_name,
            in_file_slot=tuple(in_file_slot),
            in_net_ip=in_net_ip,
        )

    def record(self) -> dict[str, object]:
        """**落盘必需子集**（§3.5）：载体记录头与索引库取这里的东西。

        只含身份与定位必需项：两套凭证、名字、签发时间、签发者、桶、载体。
        **物理坐标不进落盘**（§9.2）：槽区间由载体在写入后算出（见 :meth:`SlotRange` 说明），
        路径 / 文件名 / 网络等可推导或预留字段同样不进。
        """
        return {
            "value_uuid": str(self.value_uuid),
            "value_hash": str(self.value_hash),
            "name": self.name,
            "issued": self.issued,
            "issuer": self.issuer,
            "in_bucket_name": self.in_bucket_name,
            "in_pack_name": self.in_pack_name,
        }

    @classmethod
    def from_record(cls, raw: Mapping[str, object]) -> Id:
        """由落盘子集还原 ID：:meth:`record` 的逆。

        **未知键一律忽略**（向前兼容：将来多加的落盘字段不该让旧程序拒绝读）；
        **必需键缺失即抛**：静默补默认值会把"记录损坏"伪装成"字段本来就是空"。
        `_REQUIRED_RECORD_KEYS` 即必需键清单。
        """
        missing = [key for key in _REQUIRED_RECORD_KEYS if key not in raw]
        if missing:
            raise InvalidIdError(f"ID 记录缺少必需字段: {', '.join(missing)}")
        try:
            value_uuid = ValueUuid.parse(str(raw["value_uuid"]))
            value_hash = ValueHash.parse(str(raw["value_hash"]))
            issued = int(str(raw["issued"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidIdError(f"ID 记录字段非法: {raw!r}") from exc
        return cls(
            value_uuid=value_uuid,
            value_hash=value_hash,
            # 可选字段**用 ``or ""`` 而不是 ``get(key, "")``**：键在、值是显式 null 时，
            # `str(None)` 会得到字符串 "None"——一个静默污染的幽灵名字，下游按名匹配就错了。
            name=str(raw.get("name") or ""),
            issued=issued,
            issuer=str(raw.get("issuer") or ""),
            in_bucket_name=str(raw.get("in_bucket_name") or ""),
            in_pack_name=str(raw.get("in_pack_name") or ""),
        )

    def __str__(self) -> str:
        """紧凑写法：``uuid@bucket/pack``（调试与日志用，不是落盘格式）。"""
        place = "/".join(part for part in (self.in_bucket_name, self.in_pack_name) if part)
        return f"{self.value_uuid}@{place}" if place else str(self.value_uuid)


__all__ = ["Id", "SlotRange", "ValueHash", "ValueUuid", "now_ms"]
