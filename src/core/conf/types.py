# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""配置取值域：能声明的类型、以及类型与值的判据。

**值文件是 JSON，所以类型也只认 JSON 那几种**：`int` / `float` / `bool` / `str` / `list` / `dict`，
外加 `None`。`bytes` / `datetime` / `Path` / 枚举 / 元组 / 集合在声明期就被拒——
不是洁癖，是"校验过得去"的前提：把不可能落得下去的类型挡在门外，剩下的声明就一定写得出去、
读得回来（元组落下去读回来变列表这种"类型悄悄变形"比直接报错更坏）。

类型参数可以带一层元素：`list[int]` / `dict[str, int]`，**只许一层**。再深的嵌套不接，
因为建表 / 校验的边界在这里，多一层就得回答"数组里的对象长什么样"，那是另一件事。

判据只有一条函数（:func:`check_type`），**声明与取值两侧共用**——各写一套迟早出现
"声明时放行、读回时拦下"的自相矛盾。判据的细节见下（`bool` 不冒充 `int`、`int` 值可作浮点）。
"""

from __future__ import annotations

from types import UnionType
from typing import Any, NamedTuple, Union, cast, get_args, get_origin

from core.exc import ConfigTypeError

#: 一行配置允许落盘的值域（与 JSON 的类型一一对应）
JsonValue = int | float | bool | str | list[Any] | dict[str, Any] | None

#: "声明处没有给默认值"的记号：与 `None` 分开，因为空值本身是合法的声明值
MISSING: Any = object()

#: Python 类型 → JSON Schema 的类型名（词表与校验共用一处映射）
CONFIG_TYPES: dict[object, str] = {
    int: "integer",
    float: "number",
    bool: "boolean",
    str: "string",
    list: "array",
    dict: "object",
    type(None): "null",
}


class TypeSpec(NamedTuple):
    """一个声明过的类型，规范化之后的样子。

    属性：

    - `scalar`：这一层要判的类型（`int` / `str` / `list` / `dict` …），**不含**元素信息；
    - `element`：容器元素要判的类型（`list[int]` 的 int）；标量类型为 `None`；
    - `entries`：映射的值要判的类型（`dict[str, int]` 的 int）；其余为 `None`。
    """

    scalar: object
    element: object | None = None
    entries: object | None = None


def spec_of(type_arg: object) -> TypeSpec:
    """把一个类型写法规范化成 :class:`TypeSpec`；不是允许的写法即报错。

    接受的写法：`int` / `float` / `bool` / `str` / `list` / `dict` / `None`，
    以及带一层元素的 `list[int]` / `dict[str, int]`。其余（`bytes`、元组、嵌套泛型、
    可选联合里的非空项……）一律拒绝，理由见模块说明。
    """
    if type_arg is None:
        return TypeSpec(type(None))
    if isinstance(type_arg, type):
        if type_arg in CONFIG_TYPES:
            return TypeSpec(type_arg)
        raise ConfigTypeError(
            f"配置类型 {type_arg!r} 落不成 JSON：可用的是 "
            "int / float / bool / str / list / dict（可带一层元素）与 None"
        )

    origin = get_origin(type_arg)
    arguments = get_args(type_arg)
    if origin is list and len(arguments) == 1:
        return TypeSpec(list, element=_element_of(arguments[0]))
    if origin is dict and len(arguments) == 2:
        return TypeSpec(dict, entries=_element_of(arguments[1]))
    if origin in (Union, UnionType):
        # `int | None` 这类可空写法：除 None 外只能有一项，且那一项自己得合法。
        rest = [item for item in arguments if item is not type(None)]
        if len(rest) == 1 and len(arguments) == 2:
            return spec_of(rest[0])
    raise ConfigTypeError(
        f"配置类型 {type_arg!r} 不是允许的写法：只收内置类型、`list[元素]`、`dict[键, 值]`"
        "（一层），以及 `X | None`"
    )


def _element_of(element: object) -> object:
    """容器元素的类型：只收内核类型，不许再是容器。"""
    inner = spec_of(element)
    if inner.scalar in {list, dict}:
        raise ConfigTypeError(
            f"配置类型 {element!r} 嵌套过深：容器元素只能是 int / float / bool / str"
        )
    return inner.scalar


def check_type(value: JsonValue, spec: TypeSpec) -> JsonValue:
    """按 :class:`TypeSpec` 判一个值合不合规；不合规即抛 :class:`ConfigTypeError`。

    **返回判过的值**，可能与入参不等：整数在 `float` 类型的键上被提升成浮点
    （见下），于是调用方拿到的一定是"能原样落盘、读回来还是它"的那个值。

    判据三条：

    1. 判等用 `type(value) is 类型`，**不用 `isinstance`**——`isinstance(True, int)` 为真，
       但 `bool` 与 `int` 在 JSON 里是两个东西，`type=int` 配 `True` 必须拦下；
    2. **唯一放宽的是 `int` 值配 `float` 类型**（无损提升）；放宽后**按浮点算**：
       默认值 `1` 在 `type=float` 的键上落成 `1.0`，否则读回来是整数，会自己把自己拦下；
    3. 反向（`type=int` 配 `1.5`）一律报错，哪怕值是整数值的浮点也不放行。
    """
    if spec.scalar is list:
        if not isinstance(value, list):
            raise _mismatch(value, "list")
        raw: list[Any] = value
        if spec.element is None:
            return raw
        return [_scalar(item, spec.element) for item in raw]
    if spec.scalar is dict:
        if not isinstance(value, dict):
            raise _mismatch(value, "dict")
        raw_dict: dict[str, Any] = value
        if spec.entries is None:
            return raw_dict
        return {key: _scalar(item, spec.entries) for key, item in raw_dict.items()}
    return _scalar(value, spec.scalar)


def _scalar(value: object, expected: object) -> JsonValue:
    """判一个标量（或容器元素）：`int` 值在浮点类型上被提升，其余要求类型同一。"""
    if expected is float and type(value) is int:
        return float(value)  # 唯一放宽：无损提升，按浮点算
    if type(value) is not expected:
        raise _mismatch(value, getattr(expected, "__name__", str(expected)))
    return cast("JsonValue", value)  # 上一行已判过类型同一


def _mismatch(value: object, expected: str) -> ConfigTypeError:
    """类型与值对不上时的报错：两边的类型名都写出来，便于一眼看出错在哪。"""
    return ConfigTypeError(f"配置值的类型是 {type(value).__name__}，声明要的是 {expected}")
