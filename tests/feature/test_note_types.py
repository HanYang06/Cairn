# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from core.types import ValueUuid
from feature.note import (
    CanvasBody,
    CanvasData,
    Form,
    Graphic,
    Line,
    Link,
    Note,
    NoteData,
    Paint,
    Style,
    access_ref,
    canvas_ref,
    is_marker,
)

SVC = Note(None)  # 操作在域服务；这些操作不碰存储


def _graphic(**overrides: object) -> Graphic:
    values: dict[str, object] = {"form": Form.CIRCLE, "cx": 0.0, "cy": 0.0, "w": 2.0, "h": 2.0}
    values.update(overrides)
    return Graphic(**values)  # type: ignore[arg-type]


def _texts(note: NoteData) -> list[str]:
    return [line["v"] for line in note.body]  # type: ignore[misc]


def test_style_roundtrips_through_data() -> None:
    style = Style(bold=True, font="serif")
    assert Style.from_data(style.to_data()) == style


def test_graphic_serializes_to_numbers_and_back() -> None:
    graphic = Graphic(
        form=Form.PARALLELOGRAM,
        cx=1.5,
        cy=2.5,
        w=10.0,
        h=4.0,
        rot=0.5,
        scale=0.25,
        points=[0.0, 0.0, 1.0, 1.0],
        params=[3.0],
        paint=Paint(stroke=0xFF0000FF, width=2.0, fill=0x00FF00FF, grad=45.0, closed=True),
    )
    seq = graphic.to_seq()
    assert all(isinstance(value, float) for value in seq)
    assert Graphic.from_seq(seq) == graphic


def test_paint_serializes_to_numbers_and_back() -> None:
    paint = Paint(
        stroke=0x12345678,
        width=1.5,
        line=Line.DASHED,
        fill=0xABCDEF00,
        fill2=0x00ABCDEF,
        grad=90.0,
        alpha=0.5,
        closed=True,
    )
    seq = paint.to_seq()
    assert all(isinstance(value, float) for value in seq)
    assert Paint.from_seq(seq) == paint


def test_canvas_body_roundtrips_graphics_and_links() -> None:
    body = CanvasBody(
        graphics=[_graphic(), _graphic(form=Form.POLYGON, cx=5.0)],
        links=[Link(src=0, dst=1, kind=Line.CURVE)],
    )
    data = body.to_data()
    assert all(isinstance(seq, list) for seq in data["g"])
    assert data["l"] == [[0.0, 1.0, float(Line.CURVE)]]
    restored = CanvasBody.from_data(data)
    assert restored.graphics == body.graphics
    assert restored.links == body.links
    assert restored.mode == body.mode


def test_canvas_body_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="未知画板模式"):
        CanvasBody(mode="dragram")
    with pytest.raises(ValueError, match="未知画板模式"):
        CanvasBody.from_data({"m": "dragram"})


def test_canvas_body_hash_tracks_in_place_edit() -> None:
    canvas = CanvasData(graphics=[_graphic()])
    before = canvas.body_hash()

    canvas.graphics.append(_graphic(cx=9.0))  # 就地改动，没人调 refresh()

    assert canvas.body_hash() != before


def test_body_is_lines_with_stable_ids() -> None:
    note = NoteData()
    note.body = ["第一行\n第二行"]
    assert _texts(note) == ["第一行", "第二行"]
    ids = [line["id"] for line in note.body]
    assert all(ids)
    assert len(set(ids)) == 2
    assert note.text == "第一行\n第二行"


def test_empty_line_is_kept() -> None:
    note = NoteData()
    note.body = ["甲", "", "乙"]
    assert _texts(note) == ["甲", "", "乙"]
    assert note.text == "甲\n\n乙"


def test_markers_are_own_lines() -> None:
    note = NoteData()
    note.body = ["文字", canvas_ref(0), access_ref(1), "尾"]
    assert [line["v"] for line in note.body] == [
        "文字",
        {"canvas": 0},
        {"access": 1},
        "尾",
    ]
    assert is_marker(note.body[1]["v"])


def test_line_style_range_roundtrip() -> None:
    note = NoteData()
    note.body = ["床前明月光"]
    lid = note.body[0]["id"]
    note.style = {lid: [{(2, 4): Style(bold=True)}]}
    stored = note.style
    assert stored[lid] == [{(2, 4): Style(bold=True)}]


def test_style_overlay_later_wins() -> None:
    note = NoteData()
    note.body = ["abcdef"]
    lid = note.body[0]["id"]
    note.style = {lid: [{(0, 4): Style(bold=True)}, {(2, 6): Style(italic=True)}]}
    resolved = note.style[lid][0]
    assert resolved == {(0, 2): Style(bold=True), (2, 6): Style(italic=True)}


def test_note_typed_canvas_and_marker() -> None:
    canvas = CanvasData(graphics=[_graphic()])
    note = NoteData()
    note.body = ["床前明月光，", canvas_ref(0), "低头思故乡"]
    note.canvas = [str(canvas.oid)]

    assert note.body[1]["v"] == {"canvas": 0}
    assert note.text == "床前明月光，\n低头思故乡"
    assert note.canvas == [str(canvas.oid)]
    assert canvas.graphics == [_graphic()]


def test_note_typed_access_and_marker() -> None:
    oid = str(ValueUuid.new())
    note = NoteData()
    note.body = ["图：", access_ref(0)]
    note.access = [oid]

    assert note.body[1]["v"] == {"access": 0}
    assert note.access == [oid]
    assert note.references == (oid,)


def test_add_access_embeds_into_body() -> None:
    note = NoteData()
    note.body = ["看图"]
    note.access = []
    entry = str(ValueUuid.new())
    note.access = [*note.access, entry]
    SVC._append_marker(note, access_ref(0))
    assert note.body[-1]["v"] == {"access": 0}
    assert note.access[0] == entry


def test_reorder_keeps_style_by_line_id() -> None:
    note = NoteData()
    note.body = ["a", "b", "c"]
    ids = [line["id"] for line in note.body]
    note.style = {ids[0]: [{(0, 1): Style(bold=True)}], ids[2]: [{(0, 1): Style(italic=True)}]}

    SVC.reorder(note, [2, 0, 1])

    assert _texts(note) == ["c", "a", "b"]
    assert note.style[ids[2]][0][(0, 1)] == Style(italic=True)
    assert note.style[ids[0]][0][(0, 1)] == Style(bold=True)


def test_set_text_preserves_line_ids_and_markers() -> None:
    note = NoteData()
    note.body = ["前面", {"access": 0}, "后面"]
    note.access = [str(ValueUuid.new())]
    marker_id = note.body[1]["id"]

    SVC.set_text(note, "前面后面改")

    assert note.body[0]["v"] == "前面后面改"
    assert note.body[1]["id"] == marker_id
    assert note.body[1]["v"] == {"access": 0}


def test_body_hash_is_content_only() -> None:
    left = NoteData()
    left.body = ["hello", "world"]
    right = NoteData()
    right.body = ["hello", "world"]  # 行 id 不同

    assert left.body.hash == right.body.hash

    left.title = "A"
    right.title = "B"
    right.author = "韩"
    assert left.body.hash == right.body.hash  # 属性 / 作者不进哈希

    right.body = ["hello", "cairn"]
    assert left.body.hash != right.body.hash


def test_body_hash_tracks_style() -> None:
    left = NoteData()
    left.body = ["hello"]
    right = NoteData()
    right.body = ["hello"]
    lid = right.body[0]["id"]
    right.style = {lid: [{(0, 3): Style(bold=True)}]}

    assert left.body.hash != right.body.hash
    assert right.body.hash == right.body.hash


def test_graphic_rejects_bad_point_count() -> None:
    with pytest.raises(ValueError, match="点数"):
        Graphic.from_seq([0, 0, 0, 0, 0, 0, 0, -1, 0])


def test_link_requires_three_values() -> None:
    with pytest.raises(ValueError, match="连线"):
        Link.from_seq([0, 1])


def test_paint_requires_eight_values() -> None:
    with pytest.raises(ValueError, match="画法"):
        Paint.from_seq([0, 1, 2])


def test_normalize_body_bare_string_splits_lines() -> None:
    note = NoteData()
    note.body = "a\nb"

    assert [line["v"] for line in note.body] == ["a", "b"]


def test_references_skips_invalid_ids() -> None:
    note = NoteData()
    valid = ValueUuid.new()
    note.access = [str(valid), "not-an-oid", ""]

    assert note.references == (valid,)
