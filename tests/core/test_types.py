# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""值类型契约：**落盘**与**可索引**是两件事，`Attr` / `Body` 管的是后者。

本文件钉五件事：

- **类体上是声明**：`title: str = Attr("")` 声明落点，类型仍是 `str`；
- **实例里是裸值**：取出来就是那个值，就地增改原样生效，且不串实例、不污染类属性；
- **声明活得比赋值更久**：`note.lines = [...]` 只换值，落点仍由类体上的声明说了算；
- **裸赋值不进反表**：照样落盘，但拿不到索引加持；
- **`Body` 不带 ID**：内容的身份是算出来的摘要，不另签身份——否则去重无从谈起。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.storage.engine import Block
from core.storage.types import (
    ATTR_KIND,
    BODY_KIND,
    Attr,
    Body,
    declaration_of,
    kind_of,
    kinds_of,
    unwrap,
)

if TYPE_CHECKING:
    from core.storage.db.id import ID


class Note(Block):
    """一个把三类写法都用上的类型：可索引属性、内容、裸赋值。"""

    # 注：注解写字段的类型（str），右值是声明本身（Attr）；描述符在实例上交出 str。
    title: str = Attr("")  # type: ignore[assignment]
    lines: list[str] = Body([])  # type: ignore[assignment]
    scratch: str = ""

    def __init__(self, id: ID | None = None) -> None:
        """只收身份（本文件多数用例不落盘，故允许空身份）。"""
        if id is not None:
            super().__init__(id)


# ---- 类体上是声明 ----


def test_a_declaration_on_the_class_body_reads_as_a_bare_value():
    """取值取到的是**那个值**，不是声明对象。"""
    note = Note()

    assert note.title == ""
    assert isinstance(note.title, str)


def test_the_class_itself_still_hands_back_the_declaration():
    """类上拿到的是声明本身（`Note.__dict__["title"]` 就是那个描述符）。"""
    declaration = Note.__dict__["title"]

    assert isinstance(declaration, Attr)
    assert declaration.default == ""


def test_the_field_keeps_its_own_type():
    """**类型与语法对得上**：`title` 是 `str`、`lines` 是 `list[str]`，不是声明类型。"""
    note = Note()
    note.title = "标题"
    note.lines = ["第一行"]

    assert note.title == "标题"
    assert note.lines == ["第一行"]


# ---- 实例里是裸值 ----


def test_an_instance_stores_its_own_value():
    """赋值写进**实例自己的** `__dict__`，故两个实例互不影响。"""
    first, second = Note(), Note()
    first.title = "第一篇"

    assert first.title == "第一篇"
    assert second.title == "", "默认值没有被第一个实例改掉"


def test_mutating_a_body_in_place_affects_only_that_instance():
    """就地增改改的是这个实例那一份：既不污染类属性，也不串到别的实例。"""
    first, second = Note(), Note()

    first.lines.append("第一行")

    assert first.lines == ["第一行"]
    assert second.lines == [], "另一个实例不受影响"
    assert Note.__dict__["lines"].default == [], "类体上的默认值也没被改掉"


def test_the_declaration_outlives_the_assignment():
    """**声明活得比赋值更久**：`lines = [...]` 只换值，落点仍由类体上的声明说了算。"""
    note = Note()
    note.lines = ["第一行", "第二行"]

    assert kind_of(Note, "lines") == BODY_KIND


# ---- 判据 ----


def test_the_three_kinds_do_not_overlap():
    """`kind_of` 只认类体上的声明，裸赋值一律是"普通"（空串）。"""
    assert kind_of(Note, "title") == ATTR_KIND
    assert kind_of(Note, "lines") == BODY_KIND
    assert kind_of(Note, "scratch") == ""
    assert kind_of(Note, "id") == ""
    assert kind_of(Note, "nobody") == ""


def test_kinds_of_lists_every_declaration():
    """一份清单：字段名 → 落点，普通赋值不在里面。"""
    assert kinds_of(Note) == {"title": ATTR_KIND, "lines": BODY_KIND}


def test_a_subclass_overrides_its_parent():
    """子类重写父类的声明即以后者为准。"""

    class Child(Note):
        """把内容字段改成可索引属性。"""

        lines: list[str] = Attr([])  # type: ignore[assignment]

    assert kind_of(Child, "lines") == ATTR_KIND
    assert kinds_of(Child)["title"] == ATTR_KIND


def test_declaration_of_finds_the_declaration():
    """按名字取声明；没有声明即 `None`。"""
    assert isinstance(declaration_of(Note, "title"), Attr)
    assert isinstance(declaration_of(Note, "lines"), Body)
    assert declaration_of(Note, "scratch") is None


def test_an_empty_value_is_still_a_declaration():
    """**空值也是值**：`Attr(None)` 说的是"这个字段的值是空"，
    与"这个字段没声明过"是两件事——判据看的是声明，不是值的真假。
    """
    assert unwrap(Attr(None)) is None
    assert isinstance(declaration_of(Note, "title"), Attr)


def test_a_body_holds_no_identity():
    """`Body` 上没有任何身份字段：内容的身份是摘要，算出来而不是签出来。"""
    assert not hasattr(Body([]), "id")
    assert not hasattr(Body([]), "value_uuid")


def test_an_attr_carries_a_description_that_is_only_for_reading():
    """`doc` 给人看：它不参与取值，也不参与任何落盘或索引判据。

    **没有 `indexed` 开关**：写成 `Attr(...)` 就是"要按它查"，用了它必然进反表。
    """
    plain = Attr("")
    described = Attr("", doc="标题")

    assert plain.doc == ""
    assert described.doc == "标题"
    assert not hasattr(described, "indexed")


def test_containers_are_values_like_scalars():
    """容器不另立类型：`list` / `dict` 与标量同样是值，落点由 `Attr` / `Body` 决定。"""
    assert unwrap(Attr({"k": "v"})) == {"k": "v"}
    assert unwrap(Body([1, 2, 3])) == [1, 2, 3]


def test_unwrap_leaves_an_undeclared_value_alone():
    """没声明过的东西原样返回。"""
    assert unwrap("普通值") == "普通值"
    assert unwrap(None) is None


def test_a_plain_assignment_still_holds_its_value():
    """裸赋值原样保留——忠实记录，只是拿不到索引加持。"""
    note = Note()
    note.scratch = "不索引"

    assert note.scratch == "不索引"
    assert kind_of(Note, "scratch") == ""


@pytest.mark.parametrize("value", ["", 0, False, None])
def test_falsy_values_survive_a_round_trip_through_the_descriptor(value: object):
    """假值也是值：`""` / `0` / `False` / `None` 写进去、读出来一个不差。"""

    class Box(Block):
        """一个可索引字段。"""

        item: object = Attr(None)

        def __init__(self, id: ID | None = None) -> None:
            """只收身份。"""
            if id is not None:
                super().__init__(id)

    box = Box()
    box.item = value

    assert box.item == value
    assert kind_of(Box, "item") == ATTR_KIND
