# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""类型层的通用契约（身份凭证的形状与校验由 `test_id.py` 覆盖，此处不再重复）。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING, Any

import pytest

from core.types import ObjectInfo, ValueUuid
from core.types.attr import Attr

if TYPE_CHECKING:
    from collections.abc import Mapping


class _AttrsBox:
    def __init__(self) -> None:
        self.attrs: dict[str, object] = {}


class _Point:
    def __init__(self, x: int) -> None:
        self.x = x


class _Typed:
    """最小类型化值：带 ``to_data`` / ``from_data``，模拟 ``Signature`` 这类 ``item`` 元素。"""

    def __init__(self, value: int) -> None:
        self.value = value

    def to_data(self) -> dict[str, int]:
        return {"v": self.value}

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> _Typed:
        return cls(int(data["v"]))


def test_attr_item_decode_rejects_non_mapping() -> None:
    attr: Attr = Attr(item=_Point)
    attr.__set_name__(_AttrsBox, "p")
    box = _AttrsBox()
    box.attrs["p"] = [5]
    with pytest.raises(TypeError, match="映射形态"):
        _ = attr.__get__(box, _AttrsBox)


def test_attr_item_factory_encodes_each_element() -> None:
    attr: Attr = Attr(item=_Typed, factory=lambda: [_Typed(1), _Typed(2)])
    attr.__set_name__(_AttrsBox, "items")
    box = _AttrsBox()

    decoded = attr.__get__(box, _AttrsBox)

    # 默认值落成紧凑数据形态（与 __set__ 一致），取出来才是类型化对象
    assert box.attrs["items"] == [{"v": 1}, {"v": 2}]
    assert [item.value for item in decoded] == [1, 2]


def test_attr_item_tuple_default_is_encoded_per_element() -> None:
    # 容器默认值只放行不可变形态（#38）；元组同样逐元素编码成紧凑数据
    attr: Attr = Attr(item=_Typed, default=(_Typed(7),))
    attr.__set_name__(_AttrsBox, "items")
    box = _AttrsBox()

    assert [item.value for item in attr.__get__(box, _AttrsBox)] == [7]
    assert box.attrs["items"] == [{"v": 7}]


def test_attr_rejects_mutable_default() -> None:
    with pytest.raises(TypeError, match="factory"):
        Attr(default=[])
    with pytest.raises(TypeError, match="factory"):
        Attr(default={})


def test_attr_factory_gives_each_instance_its_own_container() -> None:
    attr: Attr = Attr(factory=list)
    attr.__set_name__(_AttrsBox, "items")
    first = _AttrsBox()
    second = _AttrsBox()

    one = attr.__get__(first, _AttrsBox)
    other = attr.__get__(second, _AttrsBox)

    assert one == []
    assert one is not other


def test_object_info_is_hashable_and_ignores_tags() -> None:
    oid = ValueUuid.new()
    first = ObjectInfo(
        oid=oid, type="note", mime=None, size=0, created=0, updated=0, tags={"a": None}
    )
    second = ObjectInfo(
        oid=oid, type="note", mime=None, size=0, created=0, updated=0, tags={"b": None}
    )

    assert first == second  # tags 不参与比较
    assert len({first, second}) == 1  # 因而对象本身可哈希


def test_value_types_are_frozen() -> None:
    info = ObjectInfo(
        oid=ValueUuid.new(),
        type="note",
        mime=None,
        size=0,
        created=0,
        updated=0,
    )
    with pytest.raises(FrozenInstanceError):
        info.size = 1  # type: ignore[misc]
