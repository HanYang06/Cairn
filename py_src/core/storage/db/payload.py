# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""块记录的载荷编解码：**一条记录是块记录还是内容记录，靠载荷里的保留键分辨**。

- **块记录**：载荷是一个映射，带保留键 :data:`REF_KEY`（指向内容的两套凭证）与
  保留键 :data:`ATTRS_KEY`（块自己声明的属性）；
- **内容记录**：载荷就是正文本身——领域说了算，内核不往里塞任何键。

判据只此一条：**带保留键、且键下是两套凭证**才算块记录。若拿一个业务可能用到的普通键
（例如 `body_ref`）当判据，一份形如 `{"body_ref": …}` 的正文就会被误判成块记录，
去重失效、列举整体报错。前缀即"业务数据不可能占用"的命名空间。

**块名不写进载荷**：写进去会让"同一份属性"因类名不同而算出两个摘要，去重就被类名切碎。
块的类型由调用它的那个类给出，查表走登记表——载荷只承载值。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import cbor2

from core.exc import AttrTypeError

if TYPE_CHECKING:
    from collections.abc import Mapping

REF_KEY = "\x00cairn.ref"
"""块记录载荷里的保留键：**指向内容的两套凭证**。"""

ATTRS_KEY = "\x00cairn.attrs"
"""块记录载荷里的保留键：块自己声明的属性（含 `Body` 字段的值）。"""

TOMBSTONE_KEY = "\x00cairn.tombstone"
"""墓碑载荷的保留键：**这一条记录标记某个载荷摘要已被删除**。

载体是追加写，旧字节删不掉；删除因此是一条追加的标记，而不是抹掉什么。
GC 靠它认出可以回收的字节。
"""

INDEX_KEY = "\x00cairn.index"
"""索引载荷的保留键：**这是一批"值 → 块身份"的条目**。

索引块是块，但它的载荷不是"某个块的属性"，而是一批反表条目。故它自带一个保留键——
判据落在载荷上，与块记录、内容记录互不混淆。"""

INDEX_OWNER_KEY = "owner"
"""索引条目里"谁建的这批索引"：建它的那个**索引块**的身份（字符串）。"""

INDEX_FIELD_KEY = "field"
"""索引条目里的字段名（属性名；`BodyIndex` 用 `content`）。"""

INDEX_VALUE_KEY = "value"
"""索引条目里的值。"""

INDEX_BLOCKS_KEY = "blocks"
"""这一行属于哪个块（身份）。"""

INDEX_VALUES_KEY = "values"
"""值的**原样文本**（给人看与显示用）；判据走带类型名的那一份。"""

UUID_KEY = "value_uuid"
"""指针里的分配形态凭证键名。"""

HASH_KEY = "value_hash"
"""指针里的摘要形态凭证键名。"""


@dataclass(frozen=True, slots=True)
class ContentRef:
    """指向内容记录的指针：**两套凭证都带**。

    只带摘要时，"这份内容被哪些块引用"只写得出一半——另一半（分配形态）是内容记录自己的
    身份，丢了它就只能指向"那份内容"，指不到"那一条内容记录"。
    """

    value_uuid: str
    value_hash: str

    def to_record(self) -> dict[str, str]:
        """编进载荷的映射形态。"""
        return {UUID_KEY: self.value_uuid, HASH_KEY: self.value_hash}

    @staticmethod
    def from_record(raw: Mapping[str, object]) -> ContentRef:
        """由载荷里的映射还原指针；两样缺一即抛，不补。"""
        uuid = raw.get(UUID_KEY)
        content = raw.get(HASH_KEY)
        if not isinstance(uuid, str) or not uuid:
            raise ValueError(f"指针缺少分配形态凭证: {raw!r}")
        if not isinstance(content, str) or not content:
            raise ValueError(f"指针缺少摘要形态凭证: {raw!r}")
        return ContentRef(value_uuid=uuid, value_hash=content)


def encode_block(attrs: Mapping[str, object], ref: ContentRef) -> bytes:
    """把块记录编成 canonical CBOR：**指针必带，属性非空才写**。

    规范化是必须的：同一份载荷每次都要编出同一段字节，否则块身份（载荷摘要）会漂。
    canonical 编码由 cbor2 保证（映射键按长度与字节序排）。
    """
    payload: dict[str, object] = {REF_KEY: ref.to_record()}
    if attrs:
        payload[ATTRS_KEY] = dict(attrs)
    try:
        return cbor2.dumps(payload, canonical=True)
    except cbor2.CBOREncodeError as error:
        raise AttrTypeError(f"块属性编不进载荷: {error}") from error


def encode_content(value: object) -> bytes:
    """把内容记录的正文编成 canonical CBOR。

    内容是领域说了算的结构：字符串、列表、字典都行，**但必须确定性编码**——
    否则同一逻辑内容会算出不同地址，去重失效、占用回升。
    """
    try:
        return cbor2.dumps(value, canonical=True)
    except cbor2.CBOREncodeError as error:
        raise AttrTypeError(f"内容编不进载荷: {error}") from error


def decode_content(payload: bytes) -> object:
    """把内容记录的载荷解回值。"""
    try:
        return cbor2.loads(payload)
    except cbor2.CBORDecodeError as error:
        raise AttrTypeError(f"内容记录解不出来: {error}") from error


def decode_block(payload: bytes) -> tuple[ContentRef, dict[str, object]] | None:
    """从记录载荷里取出（指针，属性）；**不是块载荷**即返回 ``None``（那它就是内容）。

    判据只有一条：载荷是不是一个带保留键的映射，且键下是两套凭证。解不成映射、
    映射里没有保留键、或凭证不全，都算"这是内容记录"，不猜、不降级。

    属性是**可选**的：没有那个键就是"这块没有属性"，不是错。
    """
    try:
        decoded = cbor2.loads(payload)
    except cbor2.CBORDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    raw = decoded.get(REF_KEY)
    if not isinstance(raw, dict):
        return None
    try:
        ref = ContentRef.from_record(raw)
    except (TypeError, ValueError):
        return None
    attrs = decoded.get(ATTRS_KEY)
    return ref, dict(attrs) if isinstance(attrs, dict) else {}


def content_ref_of(payload: bytes) -> ContentRef | None:
    """只取指针（块身份核对与巡检的常用面）；不是块载荷即 ``None``。"""
    parsed = decode_block(payload)
    return None if parsed is None else parsed[0]


def encode_tombstone(victim_hash: str) -> bytes:
    """把一条墓碑编成载荷：**这个载荷摘要已被删除**。"""
    return cbor2.dumps({TOMBSTONE_KEY: victim_hash}, canonical=True)


def decode_tombstone(payload: bytes) -> str | None:
    """从记录载荷里取出墓碑标记的摘要；**不是墓碑**即返回 ``None``。"""
    try:
        decoded = cbor2.loads(payload)
    except cbor2.CBORDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    victim = decoded.get(TOMBSTONE_KEY)
    return victim if isinstance(victim, str) and victim else None


def encode_index(
    owner: str,
    field: str,
    value: object,
    blocks: list[str],
    values: list[str] | None = None,
) -> bytes:
    """把**一条正表行**编成载荷：**谁建的、哪个字段、什么值、属于哪个块**。

    这里记的是**正表**：某个块的这个字段等于这个值。反表（值 → 哪些块）由读取端把这些行
    翻过来现算，**不另存一份**——存下来的反表要在写路径上增量维护，漏一处不报错、只是查不到。

    `value` 落成两份：`INDEX_VALUE_KEY` 带类型名（判据用，免得 `1` 与 `True` 相撞）、
    `INDEX_VALUES_KEY` 是给读的人看的原样文本。`blocks` 与 `values` 一一对应。
    """
    entry: dict[str, object] = {
        INDEX_OWNER_KEY: owner,
        INDEX_FIELD_KEY: field,
        INDEX_VALUE_KEY: index_text(value),
        INDEX_BLOCKS_KEY: list(blocks),
        INDEX_VALUES_KEY: list(values) if values is not None else [],
    }
    return cbor2.dumps({INDEX_KEY: entry}, canonical=True)


def decode_index(payload: bytes) -> tuple[str, str, str, list[str], list[str]] | None:
    """从记录载荷里取出一批索引行；**不是索引载荷**即返回 ``None``。

    返回（索引类型名，字段名，带类型名的值，块身份，原样文本）。
    """
    try:
        decoded = cbor2.loads(payload)
    except cbor2.CBORDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    entry = decoded.get(INDEX_KEY)
    if not isinstance(entry, dict):
        return None
    owner = entry.get(INDEX_OWNER_KEY)
    field = entry.get(INDEX_FIELD_KEY)
    value = entry.get(INDEX_VALUE_KEY)
    blocks = entry.get(INDEX_BLOCKS_KEY)
    texts = entry.get(INDEX_VALUES_KEY)
    if not isinstance(owner, str) or not isinstance(field, str) or not isinstance(value, str):
        return None
    if not isinstance(blocks, list):
        return None
    return (
        owner,
        field,
        value,
        [str(item) for item in blocks],
        [str(item) for item in texts] if isinstance(texts, list) else [],
    )


def index_text(value: object) -> str:
    """把索引值文本化：**带上类型名**，免得 `1` 与 `True` 撞在一起。

    （Python 里 `1 == True` 且哈希相同，不带类型名就会串。）读与写两侧共用这一条口径，
    故查的时候写 `1` 不会查到 `True`。
    """
    return f"{type(value).__name__}:{value}"


__all__ = [
    "ATTRS_KEY",
    "HASH_KEY",
    "INDEX_KEY",
    "REF_KEY",
    "TOMBSTONE_KEY",
    "UUID_KEY",
    "ContentRef",
    "content_ref_of",
    "decode_block",
    "decode_content",
    "decode_index",
    "decode_tombstone",
    "encode_block",
    "encode_content",
    "encode_index",
    "encode_tombstone",
    "index_text",
]
