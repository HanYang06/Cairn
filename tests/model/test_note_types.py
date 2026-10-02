# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""笔记数据结构的契约：表名、类体声明、可变默认值、身份、行载荷的判别联合与区间。

钉的是新范式的几条口径：**表名只由类名算出**、**落点声明写在类体上**、
**零参构造自己签发身份**、**声明里的容器不串实例**；以及原有的两条领域判据：
行载荷与行类型必须配套、区间半开且有序。
"""

from __future__ import annotations

from typing import Any

import pytest

from core.clock import now_ms
from core.storage.db.id import ID
from core.storage.engine import Block
from core.storage.types import declaration_of
from model.note.exc import LineShapeError, SpanRangeError
from model.note.types import (
    CanvasLink,
    Chunk,
    Code,
    Figure,
    Heading,
    LineKind,
    Link,
    ListItem,
    NoteAsset,
    NoteCanvas,
    NoteData,
    NoteGroup,
    NoteLine,
    NoteTag,
    PlacedShape,
    Ref,
    Span,
    Todo,
    reference_table,
)

_CARRIERS = (NoteData, NoteTag, NoteGroup, NoteAsset, NoteCanvas)


def _declared_default(cls: type[object], name: str) -> Any:
    """取类体上那一份声明对象，再交还它的默认值（用例只做取证，故此处不作类型收窄）。"""
    declaration = declaration_of(cls, name)
    assert declaration is not None, f"{cls.__name__} 上没有 {name} 的声明"
    return declaration.default


# ---- 表名与类体声明 ----


def test_table_names_come_from_the_class_names():
    """**表名只由类名算出来**：五个载体各自交出类名的小写写法，没有第二个口子。"""
    assert [carrier().type_name for carrier in _CARRIERS] == [
        "notedata",
        "notetag",
        "notegroup",
        "noteasset",
        "notecanvas",
    ]


def test_the_declared_kinds_come_from_the_class_body():
    """**声明写在类体上**：声明是描述符，故与实例里那个值现在是什么无关。"""
    kinds = NoteData.declared_kinds()

    assert kinds["title"] == "attr"
    assert kinds["lines"] == "body"
    assert kinds["title"] != kinds["lines"], "声明描述的是落点，不是字段本身"


def test_a_mutable_default_does_not_leak_between_instances():
    """**可变默认值不串实例**：类体上那一份是共享的，描述符在实例第一次取值时现拷一份。"""
    first = NoteGroup()
    second = NoteGroup()

    first.notes.append("n1")

    assert first.notes == ["n1"]
    assert second.notes == []
    assert _declared_default(NoteGroup, "notes") == [], "类体上那一份没有被就地改动"


def test_a_mutable_attribute_default_does_not_leak_either():
    """`Attr({})` 与 `Body([])` 同一条路：字典默认值也现拷，改一份不影响另一份。"""
    first = NoteData()
    second = NoteData()

    first.style["background"] = "var(--color-bg)"

    assert first.style == {"background": "var(--color-bg)"}
    assert second.style == {}


# ---- 身份与时刻 ----


def test_a_zero_argument_note_signs_its_own_identity():
    """**零参构造是一个块**：身份由 `ID(self)` 现签，名字从持有者推出。"""
    note = NoteData()

    assert note.id.value_uuid
    assert note.id.name == "notedata"


def test_a_note_accepts_an_identity_signed_by_the_caller():
    """调用方签好再递进来也认：此时块**不再另签**，用的就是递进来那一个。"""
    identity = ID(NoteData)

    note = NoteData(identity)

    assert note.id is identity
    assert note.id.value_uuid == identity.value_uuid


def test_a_self_signed_note_stamps_both_times():
    """自签身份时一并盖上创建时刻：``created`` 与 ``updated`` 都是当前毫秒，且两者相等。"""
    before = now_ms()
    note = NoteData()

    assert before <= note.created <= now_ms()
    assert note.updated == note.created


def test_a_note_built_from_a_given_identity_does_not_overwrite_its_times():
    """递进身份构造时**不许覆盖读回来的时间**：那两个字段的值照旧是落在实例上的默认值。"""
    note = NoteData(ID(NoteData))

    assert note.created == 0
    assert note.updated == 0


# ---- 词表与引用落点 ----


def test_line_kind_values_are_short_names_without_prefix():
    """行类型落盘就是短名：values 换成带前缀的名字，等于改了落盘格式。"""
    assert {kind.value for kind in LineKind} == {
        "text",
        "heading",
        "list",
        "code",
        "todo",
        "link",
        "asset",
        "canvas",
        "note",
    }


def test_reference_tables_cover_only_the_kinds_with_one_target():
    """落点表只收目标唯一的那些：链接两可、内容类无目标，都不进去。"""
    assert reference_table(LineKind.ASSET) == "noteasset"
    assert reference_table(LineKind.CANVAS) == "notecanvas"
    assert reference_table(LineKind.NOTE) == "notedata"
    assert reference_table(LineKind.LINK) is None
    assert reference_table(LineKind.TEXT) is None


# ---- 区间 ----


def test_a_span_refuses_a_backwards_or_negative_range():
    """区间半开且必须有序：反着写或写负数当场报错，不留到渲染时才炸。"""
    with pytest.raises(SpanRangeError):
        Span(start=3, end=1)
    with pytest.raises(SpanRangeError):
        Span(start=-1, end=0)


# ---- 行：载荷的判别联合 ----


@pytest.mark.parametrize(
    ("kind", "data"),
    [
        (LineKind.TEXT, "正文"),
        (LineKind.HEADING, Heading("标题", level=2)),
        (LineKind.LIST, ListItem("条目", level=2, ordered=True)),
        (LineKind.CODE, Code("print(1)", language="python")),
        (LineKind.TODO, Todo("待办")),
        (LineKind.LINK, Link(target="https://example.com", label="站点")),
        (LineKind.ASSET, Ref(ids=["a", "b"])),
        (LineKind.CANVAS, Ref(ids=["c"])),
        (LineKind.NOTE, Ref(ids=["d"])),
    ],
)
def test_every_kind_accepts_its_own_payload(kind: LineKind, data: object):
    """每种行类型都收得下它自己的载荷（判别联合的正面）。"""
    assert NoteLine(kind=kind, data=data).data == data  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kind", "wrong"),
    [
        (LineKind.TEXT, Heading("标题")),
        (LineKind.HEADING, "纯文本"),
        (LineKind.ASSET, Heading("标题")),
        (LineKind.NOTE, Chunk("c1", 8)),
    ],
)
def test_a_payload_of_another_kind_is_refused(kind: LineKind, wrong: object):
    """与行类型不配套的载荷一律拒绝：读 `data` 之前必须按 `kind` 分支，判据不能破。"""
    with pytest.raises(LineShapeError):
        NoteLine(kind=kind, data=wrong)  # type: ignore[arg-type]


def test_a_plain_text_line_is_the_default_and_its_id_is_issued_per_instance():
    """缺省行就是一行纯文本；行身份默认签发，且两次构造互不相同。"""
    first, second = NoteLine(), NoteLine()

    assert first.kind is LineKind.TEXT
    assert first.data == ""
    assert first.spans == []
    assert first.id
    assert second.id
    assert first.id != second.id


def test_an_empty_note_carries_no_lines():
    """空正文合法：新建的笔记还没有行，故 `__len__` 是零。"""
    assert len(NoteData()) == 0


def test_the_canvas_payload_structures_are_not_carriers():
    """载荷内的结构是普通值对象：**不继承块**，故不建表，只随载体的载荷重建。"""
    canvas = NoteCanvas()
    canvas.shapes.append(("1", PlacedShape(figure=Figure(kind="rect"))))
    canvas.links["L1"] = CanvasLink(figures=["1"])

    assert canvas.shape("1") is not None
    assert canvas.link("L1") is not None
    assert not issubclass(PlacedShape, Block)
    assert not issubclass(CanvasLink, Block)
