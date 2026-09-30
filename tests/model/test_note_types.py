# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""笔记数据结构的契约。

钉四件事：① 行类型落盘是短名，且引用落点只有一处定义；② 样式只存非默认值、键有序，
且两个作用域互不相等；③ 行载荷是判别联合，与行类型必须始终配套；④ 正文保序且不可变。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from model.note.exc import LineShapeError, SpanRangeError
from model.note.types import (
    REFERENCE_TABLES,
    Code,
    Heading,
    LineContent,
    LineKind,
    Link,
    ListItem,
    NoteBody,
    NoteLine,
    NoteStyle,
    Ref,
    Span,
    SpanStyle,
    Todo,
    reference_table,
)

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
    """落点表只收目标唯一的那些：链接两可、内容类无目标，都不进去。

    表名带 `note` 前缀：领域专属的类型以域名开头，`project` 那边同名也不相干。
    """
    assert set(REFERENCE_TABLES) == {LineKind.ASSET, LineKind.CANVAS, LineKind.NOTE}
    assert reference_table(LineKind.ASSET) == "noteasset"
    assert reference_table(LineKind.CANVAS) == "notecanvas"
    assert reference_table(LineKind.NOTE) == "notedata"
    assert reference_table(LineKind.LINK) is None
    assert reference_table(LineKind.TEXT) is None


# ---- 样式 ----


def test_span_style_drops_empty_values_and_sorts_keys():
    """规范形态：空值等于不写，键按名排序——同一份逻辑样式必须编出同一段字节。"""
    assert SpanStyle.of({"b": "", "a": "1", "c": "2"}).values == (("a", "1"), ("c", "2"))
    assert SpanStyle.of({"b": "2", "a": "1"}).values == SpanStyle.of({"a": "1", "b": "2"}).values


def test_an_empty_style_is_falsy_and_all_empty_forms_agree():
    """没写属性就是空样式，三种造法得到同一个东西。"""
    assert not SpanStyle()
    assert not SpanStyle.of()
    assert not SpanStyle.of({})
    assert not SpanStyle.of(None)
    assert SpanStyle.of({"a": ""}) == SpanStyle()


def test_the_two_style_scopes_are_never_equal():
    """两个作用域就算内容一样也不相等：混用必须当场可见。

    左边按 `object` 拿着——静态检查知道两者类型不相交，而这里要钉的正是**运行期**那条。
    """
    span = SpanStyle.of({"a": "1"})
    note: object = NoteStyle.of({"a": "1"})
    assert note != span
    assert not isinstance(NoteStyle(), SpanStyle)
    assert not isinstance(SpanStyle(), NoteStyle)


# ---- 区间 ----


def test_span_refuses_a_backwards_or_negative_range():
    """区间半开且必须有序：反着写或写负数当场报错，不留到渲染时才炸。"""
    with pytest.raises(SpanRangeError):
        Span(start=3, end=1)
    with pytest.raises(SpanRangeError):
        Span(start=-1, end=2)


def test_an_empty_span_is_allowed_and_carries_a_default_style():
    """零宽区间合法（它在编辑中间态里是常见的），缺省样式是空样式。"""
    assert Span(start=2, end=2).style == SpanStyle()


# ---- 行：载荷的判别联合 ----

_KIND_PAYLOADS = [
    (LineKind.TEXT, "正文"),
    (LineKind.HEADING, Heading("标题", level=2)),
    (LineKind.LIST, ListItem("条目", level=2, ordered=True)),
    (LineKind.CODE, Code("print(1)", language="python")),
    (LineKind.TODO, Todo("买菜", done=False)),
    (LineKind.LINK, Link(target="https://example.com", label="站点")),
    (LineKind.ASSET, Ref(ids=("a", "b"))),
    (LineKind.CANVAS, Ref(ids=("c",))),
    (LineKind.NOTE, Ref(ids=("d",))),
]


@pytest.mark.parametrize(("kind", "data"), _KIND_PAYLOADS)
def test_every_kind_accepts_its_own_payload(kind, data):
    """每种行类型都收得下它自己的载荷（判别联合的正面）。"""
    assert NoteLine(kind=kind, data=data).data == data


@pytest.mark.parametrize(
    ("kind", "wrong"),
    [
        (LineKind.TEXT, Heading("标题")),
        (LineKind.HEADING, "纯文本"),
        (LineKind.LIST, "纯文本"),
        (LineKind.CODE, "纯文本"),
        (LineKind.TODO, "纯文本"),
        (LineKind.LINK, "纯文本"),
        (LineKind.ASSET, Heading("标题")),
        (LineKind.CANVAS, Heading("标题")),
        (LineKind.NOTE, Heading("标题")),
    ],
)
def test_every_kind_refuses_a_payload_of_another_kind(kind, wrong):
    """把别人的载荷塞进来一律拒绝。

    静态类型这一步是过得去的（`wrong` 也在 `LineData` 里），**拦住它的是运行期的判别**——
    这正是这条测要钉的东西：读 `data` 之前必须按 `kind` 分支。
    """
    with pytest.raises(LineShapeError):
        NoteLine(kind=kind, data=wrong)


def test_a_plain_text_line_is_the_default_and_its_id_is_issued_per_instance():
    """缺省行就是一行纯文本；身份默认签发，且两次构造互不相同。"""
    first, second = NoteLine(), NoteLine()
    assert first.kind is LineKind.TEXT
    assert first.data == ""
    assert first.spans == ()
    assert first.id
    assert second.id
    assert first.id != second.id


def test_spans_ride_on_the_line_and_keep_their_order():
    """样式挂在行上：读一行即得它的区间，顺序即书写顺序（后写覆盖前写靠它）。"""
    line = NoteLine(
        data="加粗的字",
        spans=(Span(start=0, end=2, style=SpanStyle.of({"font-weight": "bold"})), Span(2, 4)),
    )
    assert [span.start for span in line.spans] == [0, 2]


def test_line_content_is_the_line_minus_its_identity():
    """行内容 = 行去掉身份：三样都在，`id` 不在。"""
    line = NoteLine(data="正文", spans=(Span(start=0, end=1),))
    content = line.content
    assert content.kind is LineKind.TEXT
    assert content.data == "正文"
    assert content.spans == line.spans
    assert not hasattr(content, "id")


def test_line_content_holds_the_same_shape_rule_as_the_line():
    """内容那一层同样守着判别联合：载荷与类型对不上照样当场报错。"""
    with pytest.raises(LineShapeError):
        LineContent(kind=LineKind.HEADING, data="纯文本")


# ---- 正文 ----


def test_note_body_keeps_line_order_and_counts_lines():
    """正文外层是有序列表：行序就是它，不靠任何排序键。"""
    body = NoteBody(lines=(NoteLine(data="一"), NoteLine(data="二"), NoteLine(data="三")))
    assert [line.data for line in body.lines] == ["一", "二", "三"]
    assert len(body) == 3


def test_an_empty_body_is_empty_and_styled_by_default_off():
    """空正文合法（新建的笔记还没写），缺省样式是空样式。"""
    assert len(NoteBody()) == 0
    assert not NoteBody().style


def test_note_body_is_immutable():
    """整份不可变：编辑一次就是造一份新的（落盘也随之产生新的块身份）。

    属性名走变量，故这是**运行期**的写尝试，不是静态检查能提前挡下的那种违例。
    """
    body = NoteBody()
    attribute = "lines"
    with pytest.raises(FrozenInstanceError):
        setattr(body, attribute, ())
