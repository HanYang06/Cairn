# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
r"""槽内容的编解码：**按槽种类直接编 canonical CBOR**，没有"记录"这一层。

块的落点只有两处，故这里只有两种内容：

| 槽种类 | 内容 | 编码 |
|---|---|---|
| 属性槽 | 一块的**全部属性**（字段名 → 值），正文的字段另带 `"body": true` | :func:`encode_attrs` |
| 正文槽 | 正文分片的字节（就是块记录里那一份正文的切片） | 不编，切片即字节 |

**保留键随"记录"概念一起作废**：从前要拿保留键分辨"这一条是块记录还是内容记录"，
因为两种记录混在同一条追加流里。现在槽头自己带着槽种类，判别落在载体上，
故载荷里不再需要 `\x00cairn.*` 那一套命名空间。

索引块的正表行也走这里（:func:`encode_index_row`）：它同样是"某一格的内容"，
落点由槽头给出，内容自己不自报归属。

**属性里那个 `"body": true` 标记必须留着**：赋值一步就会覆盖 `Body(...)` 的声明，
故落点必须与值一起存下来，否则回读时分不清哪些字段的内容在正文槽里。
"""

from __future__ import annotations

import cbor2

from core.exc import AttrTypeError

__all__ = [
    "BODY_MARK",
    "COLUMN_KEY",
    "INDEX_ROW_SCHEMA",
    "VALUE_KEY",
    "decode_attrs",
    "decode_index_row",
    "encode_attrs",
    "encode_index_row",
    "index_text",
]

VALUE_KEY = "v"
"""属性条目里装值的键。"""

BODY_MARK = "body"
"""属性条目里"这个字段的内容在正文槽里"的标记。"""

COLUMN_KEY = "field"
"""索引正表行里的列名（属性名；正文那一路用它自己声明的列名）。"""

INDEX_ROW_SCHEMA = "cairn.index.row"
"""索引块正表行的模式标记：**内容与属性映射靠它区分**。

属性槽装的是"字段名 → 值"，而正表行装的是"谁、哪个字段、什么值、属于哪个块"。
两者都是 CBOR 映射，判据必须落在内容上，故正表行的映射里带这一个标记；
业务字段名不可能等于它（它带 `cairn.` 前缀与一个点）。
"""


def encode_attrs(attrs: dict[str, object]) -> bytes:
    """把一个块的全部属性编成 canonical CBOR。

    规范化是必须的：同一份属性每次都要编出同一段字节，否则"这份属性有没有变"就判不准，
    而"只写它动过的域"正是靠这个判断。

    Raises:
        AttrTypeError: 值编不进 CBOR（如 `Path`、自定义对象）。
    """
    try:
        return cbor2.dumps(dict(attrs), canonical=True)
    except cbor2.CBOREncodeError as error:
        raise AttrTypeError(f"块属性编不进槽: {error}") from error


def decode_attrs(content: bytes) -> dict[str, object]:
    """把属性槽的内容解回映射。

    Raises:
        AttrTypeError: 内容不是 CBOR，或解出来的不是映射。
    """
    try:
        decoded = cbor2.loads(content)
    except cbor2.CBORDecodeError as error:
        raise AttrTypeError(f"属性槽的内容解不出来: {error}") from error
    if not isinstance(decoded, dict):
        raise AttrTypeError(f"属性槽的内容不是映射: {type(decoded).__name__}")
    return dict(decoded)


def encode_index_row(row: dict[str, object]) -> bytes:
    """把索引块里**一条正表行**编成 canonical CBOR，并打上模式标记。

    Raises:
        AttrTypeError: 值编不进 CBOR。
    """
    payload = dict(row) | {INDEX_ROW_SCHEMA: True}
    try:
        return cbor2.dumps(payload, canonical=True)
    except cbor2.CBOREncodeError as error:
        raise AttrTypeError(f"索引行编不进槽: {error}") from error


def decode_index_row(content: bytes) -> dict[str, object] | None:
    """把一格内容解成正表行；**不是正表行即返回 `None`**（那它就是属性映射）。

    判据只有一条：映射里有没有模式标记。字段名撞上它不可能——它带 `cairn.` 前缀。
    """
    try:
        decoded = cbor2.loads(content)
    except cbor2.CBORDecodeError:
        return None
    if not isinstance(decoded, dict) or not decoded.get(INDEX_ROW_SCHEMA):
        return None
    return {key: value for key, value in decoded.items() if key != INDEX_ROW_SCHEMA}


def index_text(value: object) -> str:
    """把索引值文本化：**带上类型名**，免得 `1` 与 `True` 撞在一起。

    （Python 里 `1 == True` 且哈希相同，不带类型名就会串。）读与写两侧共用这一条口径，
    故查的时候写 `1` 不会查到 `True`。
    """
    return f"{type(value).__name__}:{value}"
