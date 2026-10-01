# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""笔记数据结构的契约：词表、行载荷的判别联合、区间、可变容器。

钉四件事：① 行类型与变更动作都是短名闭集，引用落点只有一处定义；
② 行载荷是判别联合，与行类型必须始终配套；③ 区间半开且有序；
④ 变长的容器是**列表**——编辑就地做，不必整份复制。
"""

from __future__ import annotations

import pytest

from core.storage.registry import REGISTRY
from model.note.exc import LineShapeError, SpanRangeError
from model.note.types import (
    REFERENCE_TABLES,
    Code,
    Heading,
    LineKind,
    Link,
    ListItem,
    NoteData,
    NoteLine,
    Ref,
    Span,
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


# ---- 区间 ----


def test_span_refuses_a_backwards_or_negative_range():
    """区间半开且必须有序：反着写或写负数当场报错，不留到渲染时才炸。"""
    with pytest.raises(SpanRangeError):
        Span(start=3, end=1)
    with pytest.raises(SpanRangeError):
        Span(start=-1, end=2)


def test_a_span_carries_a_plain_kv_style():
    """行内样式就是一份 KV：CSS 属性名 → CSS 值。"""
    span = Span(start=0, end=2, style={"font-weight": "bold"})
    assert span.style["font-weight"] == "bold"
    assert Span(start=2, end=2).style == {}


# ---- 行：载荷的判别联合 ----

_KIND_PAYLOADS = [
    (LineKind.TEXT, "正文"),
    (LineKind.HEADING, Heading("标题", level=2)),
    (LineKind.LIST, ListItem("条目", level=2, ordered=True)),
    (LineKind.CODE, Code("print(1)", language="python")),
    (LineKind.TODO, Todo("买菜")),
    (LineKind.LINK, Link(target="https://example.com", label="站点")),
    (LineKind.ASSET, Ref(ids=["a", "b"])),
    (LineKind.CANVAS, Ref(ids=["c"])),
    (LineKind.NOTE, Ref(ids=["d"])),
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
    这正是这条要钉的东西：读 `data` 之前必须按 `kind` 分支。
    """
    with pytest.raises(LineShapeError):
        NoteLine(kind=kind, data=wrong)


def test_a_plain_text_line_is_the_default_and_its_id_is_issued_per_instance():
    """缺省行就是一行纯文本；身份默认签发，且两次构造互不相同。"""
    first, second = NoteLine(), NoteLine()
    assert first.kind is LineKind.TEXT
    assert first.data == ""
    assert first.spans == []
    assert first.id
    assert second.id
    assert first.id != second.id


# ---- 变长容器：列表，可就地编辑 ----


def test_line_spans_are_a_list_so_they_can_be_edited_in_place():
    """行内区间是**列表**：编辑就地做，不必整份复制。"""
    line = NoteLine(data="加粗的字")
    line.spans.append(Span(start=0, end=2, style={"font-weight": "bold"}))
    line.spans.append(Span(start=2, end=4))
    assert [span.start for span in line.spans] == [0, 2]
    line.spans.clear()
    assert line.spans == []


def test_note_lines_can_be_edited_in_place_and_keep_their_order():
    """正文外层是有序列表：行序就是它，且增删就地做。"""
    note = NoteData()
    note.lines.extend([NoteLine(data="一"), NoteLine(data="二")])
    note.lines.append(NoteLine(data="三"))
    note.lines.insert(0, NoteLine(data="零"))
    note.lines.pop(2)
    assert [line.data for line in note.lines] == ["零", "一", "三"]
    assert len(note) == 3


def test_the_payload_carries_lines_and_nothing_else():
    """载荷里只有行：笔记级样式与标题一类小字段都是**属性**，跟着块走，故不进载荷。

    这条不是形式主义——放进来就等于"改一次背景把整篇重存一遍"，而载荷按内容地址去重。
    判据取自登记表：`payload` 是载荷字段，`attrs` 是属性字段。
    """
    decl = REGISTRY.get("NoteData")
    assert decl is not None
    assert decl.payload == ("lines",)
    assert "lines" not in {name for name, _ in decl.attrs}


def test_an_empty_note_has_no_lines():
    """空正文合法：新建的笔记还没有行。"""
    note = NoteData()
    assert len(note) == 0
    assert note.lines == []
