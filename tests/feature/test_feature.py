# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core import Core, ObjectNotFoundError
from core.storage import Block
from feature import (
    Note,
    Relation,
    Signature,
    known_kinds,
)

if TYPE_CHECKING:
    from core.types.event import Event


def test_registry_has_builtin_kinds() -> None:
    assert {"notedata", "asset", "projectdata"} <= set(known_kinds())


def test_note_roundtrip(core: Core) -> None:

    notes = Note(core)
    note = notes.create("hello world", title="Hi", tags=["a", "b"])

    assert note.text == "hello world"
    assert note.title == "Hi"
    assert note.tags == {"a": None, "b": None}
    assert note.info.type == "notedata"

    loaded = notes.load(note.oid)
    assert loaded.text == "hello world"


def test_note_update_preserves_created_meta(core: Core) -> None:

    notes = Note(core)
    note = notes.create("v1", title="t1", props={"color": "red"})
    before = core.info(note.oid)

    notes.update(note, text="v2")

    assert note.text == "v2"
    assert note.title == "t1"
    assert note.props()["color"] == "red"

    after = core.info(note.oid)
    assert after.created == before.created
    assert after.updated >= before.updated


def test_note_list_and_delete(core: Core) -> None:

    notes = Note(core)
    first = notes.create("a")
    second = notes.create("b")

    assert {note.oid for note in notes.list_notes()} == {first.oid, second.oid}

    core.drop(str(first.id))
    assert {note.oid for note in notes.list_notes()} == {second.oid}


def test_note_list_skips_other_block_types(core: Core) -> None:
    """库里混入非笔记块时，列笔记**不得**中断：先按类型过滤，再按命中的 id 解码。"""
    notes = Note(core)
    note = notes.create("x")
    core.put(Block(body=b"asset", type="asset"))

    assert {item.oid for item in notes.list_notes()} == {note.oid}


def test_note_list_filters_by_tags(core: Core) -> None:
    """`tags` 是签名里的承诺：给出时必须真的筛选，不得静默忽略。"""
    notes = Note(core)
    kept = notes.create("x", tags={"作者": "韩"})
    notes.create("y", tags={"作者": "石"})

    assert {item.oid for item in notes.list_notes(tags={"作者": "韩"})} == {kept.oid}


def test_change_broadcast_carries_the_subject(core: Core) -> None:
    """变更广播带上主体 oid：订阅方据此定位是哪条笔记变了。"""
    notes = Note(core)
    subjects: list[object] = []

    def on_event(event: Event) -> None:
        if not event.actions:  # 广播 = 不带动作链（带动作链的是"落盘"那类事件）
            subjects.append(event.target)

    with core.signal.subscribe(on_event):
        note = notes.create("x")

    assert subjects == [str(note.oid)]


def test_relation_load_missing_raises_not_found(core: Core) -> None:

    note = Note(core).create("x")

    with pytest.raises(ObjectNotFoundError):
        Relation.load(core, note.oid)


def test_note_authors_and_dict_tags(core: Core) -> None:

    notes = Note(core)
    note = notes.create("x", tags={"作者": "韩", "草稿": None})
    note.author = "韩"
    note.authors = ["韩", {"name": "石"}]
    notes.save(note)

    loaded = notes.load(note.oid)
    assert loaded.tags == {"作者": "韩", "草稿": None}
    assert loaded.author == "韩"
    assert loaded.authors == ["韩", {"name": "石"}]

    assert {info.oid for info in core.iter(tags={"作者": "韩"})} == {note.oid}
    assert {info.oid for info in core.iter(tags={"作者": "石"})} == set()


def test_body_pool_dedupes_across_attrs(core: Core) -> None:

    notes = Note(core)
    first = notes.create("same body", title="A")
    second = notes.create("same body", title="B")

    assert first.body.hash == second.body.hash
    stored = list(core.storage.blocks.iter_blocks())
    assert len(stored) == 2  # 两个块：属性各自独立
    assert len({block.checksum for block in stored}) == 1  # 两条指向同一份内容


def test_same_content_different_line_ids_coexist(core: Core) -> None:
    """同文但行 id 不同的两条笔记：去重键含行 id，读回不得串成别人的行 id。"""

    notes = Note(core)
    first = notes.create("same body")
    second = notes.create("same body")
    # 模拟编辑过程中行 id 变化（拆分 / 删除重插等），正文内容保持不变
    second.body.text = [dict(second.body[0], id="01ARZ3NDEKTSV4RRFFQ69G5FAV")]
    second.body.refresh()
    notes.save(second)

    assert first.body.hash == second.body.hash  # 内容签名（剥离行 id）一致
    # 负载口径不同 → 两个块指向两份内容
    assert len({block.checksum for block in core.storage.blocks.iter_blocks()}) == 2
    loaded = notes.load(second.oid)
    assert loaded.body[0]["id"] == "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def test_note_creation_signature_is_composite(core: Core) -> None:

    notes = Note(core)
    note = notes.create("正文", title="T")

    signature = note.signature
    assert isinstance(signature, Signature)
    assert signature.verify()
    assert signature.subject == note.body.hash
    assert signature.encoded().startswith("cn1.")

    loaded = notes.load(note.oid)
    assert isinstance(loaded.signature, Signature)
    assert loaded.signature.verify()
    assert loaded.signature.value == signature.value


def test_signature_tamper_is_detected() -> None:
    signature = Signature.create(author="韩", subject="abc")
    assert signature.verify()

    tampered = Signature.from_data({**signature.to_data(), "author": "石"})
    assert not tampered.verify()


def test_signature_from_data_fails_closed() -> None:
    assert Signature.from_data(None).verify() is False
    assert Signature.from_data({"created": None}).verify() is False
    with pytest.raises(TypeError):
        Signature.from_data([1])


def test_signature_created_type_is_strict() -> None:
    signature = Signature.create(author="韩", subject="abc", created=1000)
    tampered = Signature.from_data({**signature.to_data(), "created": "1000"})
    assert not tampered.verify()


def test_relation_backlinks_and_outbound(core: Core) -> None:

    notes = Note(core)
    source = notes.create("source")
    target = notes.create("target")

    relation = Relation.create(core, source.oid, target.oid, relation="annotates")
    assert relation.source == source.oid
    assert relation.target == target.oid
    assert relation.relation == "annotates"

    backlinks = [rel.oid for rel in Relation.backlinks(core, target.oid)]
    assert backlinks == [relation.oid]

    outbound = [rel.oid for rel in Relation.outbound(core, source.oid)]
    assert outbound == [relation.oid]
