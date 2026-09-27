# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""存储面的**块语义**契约：块怎么进、怎么出、坏点怎么报。

旧的 `Bucket` / `Catalog` 已退役（设计篇 §11），故这里只留与"块"有关的契约：
块的字段与编解码、写入前后的自检、按类型还原、去重、损坏检出、重开仍在；
以及**领域表**（`Storage.table`）那一组 CRUD——它就是关系行赖以存在的那张表。

已经不在这里的（随旧层一起退役，能力空缺记在设计篇 §12）：事务与回滚、
`isolated` 独占载体、大正文分片、每桶一份配置、目录版本号。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from core.storage import (
    PACKS_DIR,
    Block,
    BlockStore,
    Body,
    BodyField,
    CarrierFile,
    Storage,
    create_table,
)
from core.types import CairnError, CorruptObjectError, KindMismatchError, ObjectNotFoundError
from core.types.attr import Attr, Data

if TYPE_CHECKING:
    from pathlib import Path


class Note(Block):
    """示例领域结构：继承块，重新描述 body，声明原生属性。"""

    type = "cairn.test.note"
    body = BodyField(factory=list)
    title = Attr()
    tags = Attr(factory=list)


class Project(Block):
    type = "cairn.test.project"


class ListBody(Body):
    """内容是一个**就地可改**的 list——模拟 ``CanvasBody`` 那类暴露内部容器的 body。"""

    def __init__(self, items: list[int] | None = None) -> None:
        self.items = list(items or ())
        self.refresh()

    def content(self) -> Any:
        return {"items": list(self.items)}

    def to_data(self) -> Any:
        return {"items": list(self.items)}


class Strict(Block):
    type = "cairn.test.strict"

    def validate(self) -> None:
        if not self.attrs.get("ok"):
            raise ValueError("缺少 ok")


def _store(tmp_path: Path) -> BlockStore:
    return BlockStore.open(tmp_path / "vault")


def _storage(tmp_path: Path) -> Storage:
    return Storage.open(tmp_path / "vault")


# ---- 块本身：字段、编解码、自检 ----


def test_body_default_and_edit() -> None:
    note = Note()
    assert note.body == []
    note.body.append("正文")
    assert note.body == ["正文"]


def test_body_hash_recomputes_after_in_place_edit() -> None:
    """就地改动内部容器后，去重键必须跟着变（缓存会让去重键与负载脱钩）。"""
    block = Block(body=ListBody([1]))
    before = block.body_hash()

    block.body.items.append(2)

    assert block.body_hash() != before


def test_read_rejects_non_bytes_body() -> None:
    note = Note()
    note.body = ["第一行"]

    with pytest.raises(TypeError, match="body 不是字节"):
        note.read()


def test_read_rejects_structured_body() -> None:
    block = Block(body=ListBody([1]))

    with pytest.raises(TypeError, match="encode_body"):
        block.read()


def test_read_accepts_bytearray() -> None:
    block = Block(body=bytearray(b"raw"))

    assert block.read() == b"raw"


def test_id_is_locked() -> None:
    note = Note()
    with pytest.raises(AttributeError):
        note.id = "another-id"


def test_block_decode_requires_id() -> None:
    with pytest.raises(CorruptObjectError):
        Block.decode(b"")


def test_data_annotation_becomes_data_field() -> None:
    class Holder(Block):
        type = "test.holder.data"
        items: Data[list[str]] = []  # noqa: RUF012 — 测试声明，验证注解路由

    assert isinstance(Holder.__dict__["items"], Data)


# ---- 进与出 ----


def test_object_edit_roundtrip(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        note = Note()
        note.title = "Hello"
        note.body.append("正文")
        note.tags = {"a": None}
        returned = store.store(note)
        assert returned is note
        assert note.checksum

        loaded = store.get(Note, note.id)
        assert isinstance(loaded, Note)
        assert loaded.id == note.id
        assert loaded.title == "Hello"
        assert loaded.body == ["正文"]
        assert loaded.tags == {"a": None}


def test_same_content_dedupes_physically(tmp_path: Path) -> None:
    """同 body 的两个块：块各一条，内容只有一份（去重在内容面）。"""
    with _store(tmp_path) as store:
        first = Note(body=["same"])
        second = Note(body=["same"])
        store.store(first)
        store.store(second)
        assert first.id != second.id

        copies = [
            record
            for _place, record in store.vault.records()
            if record.id.value_hash == first.checksum
        ]
        assert len(copies) == 1
        assert {block.id for block in store.iter_blocks()} == {first.id, second.id}


def test_unknown_type_falls_back_to_base(tmp_path: Path) -> None:
    """类型由程序给出（§3.5）：不认识就降级读回，不抛错、不丢弃。"""
    with _store(tmp_path) as store:
        block = Block(type="cairn.test.unknown", body=["x"])
        store.store(block)
        loaded = store.get(Block, block.id)
        assert type(loaded) is Block
        assert loaded.type == "cairn.test.unknown"


def test_wrong_class_is_rejected(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        note = Note()
        store.store(note)
        with pytest.raises(KindMismatchError):
            store.get(Project, note.id)


def test_decode_rebuilds_subclass(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        note = Note(body=["x"])
        note.title = "T"
        store.store(note)
        decoded = store.get(Block, note.id)
        assert isinstance(decoded, Note)
        assert decoded.title == "T"


def test_validation_runs_on_put(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        with pytest.raises(ValueError, match="缺少 ok"):
            store.store(Strict())
        good = Strict(attrs={"ok": True})
        store.store(good)
        assert store.get(Strict, good.id).attrs == {"ok": True}


def test_author_persists(tmp_path: Path) -> None:
    """作者是块的**顶层字段**（不在 attrs 里），故读回时必须单独补。"""
    with _store(tmp_path) as store:
        note = Note(body=["x"])
        note.author = "韩"
        store.store(note)
        assert store.get(Note, note.id).author == "韩"


def test_block_metadata_fields(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        note = Note()
        note.body.append("v1")
        store.store(note)
        assert note.created > 0
        assert note.updated > 0
        assert note.size > 0


def test_fields_and_config_persist(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        note = Note()
        note.title = "T"
        note.body.append("x")
        note.config["write"] = "x"
        store.store(note)

        loaded = store.get(Note, note.id)
        assert loaded.size == note.size
        assert loaded.created == note.created
        assert loaded.updated == note.updated
        assert loaded.config == {"write": "x"}


def test_persistence_across_reopen(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        note = Note()
        note.body.append("persist")
        store.store(note)

    with BlockStore.open(tmp_path / "vault") as reopened:
        loaded = reopened.get(Note, note.id)
        assert isinstance(loaded, Note)
        assert loaded.body == ["persist"]


def test_delete_removes_object(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        note = Note()
        store.store(note)
        assert store.drop(note.id) is True
        with pytest.raises(ObjectNotFoundError):
            store.get(Note, note.id)
        assert store.drop(note.id) is False


def test_iter_blocks_streams(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        store.store(Note(body=["x"]))
        blocks = store.iter_blocks()
        assert iter(blocks) is blocks  # 生成器：不整表物化
        assert list(blocks)


# ---- 坏点：报出来，不装作没事 ----


def test_corruption_is_detected(tmp_path: Path) -> None:
    """载体里的字节被改 → 按摘要不符报损坏，不返回半份内容。"""
    with _store(tmp_path) as store:
        note = Note(body=["good"])
        store.store(note)
        place = store.vault.placement(note.id)
        assert place is not None
        path = store.vault.root / place.bucket / PACKS_DIR / place.pack

        carrier = CarrierFile.open(path)
        offset = carrier.layout.offset_of_span(place.span)
        raw = bytearray(path.read_bytes())
        raw[offset + place.size - 1] ^= 0xFF
        path.write_bytes(bytes(raw))

        with pytest.raises(CorruptObjectError):
            store.fetch(note.id)


def test_content_corruption_is_reported(tmp_path: Path) -> None:
    """块记录的载荷没坏、坏的是它指向的 body → 读块时必须报出来。"""
    with _store(tmp_path) as store:
        note = Note(body=["x"])
        store.store(note)
        content = next(
            place
            for place, record in store.vault.records()
            if record.id.value_hash == note.checksum
        )
        path = store.vault.root / content.bucket / PACKS_DIR / content.pack

        carrier = CarrierFile.open(path)
        offset = carrier.layout.offset_of_span(content.span)
        raw = bytearray(path.read_bytes())
        raw[offset + content.size - 1] ^= 0xFF
        path.write_bytes(bytes(raw))

        with pytest.raises(CorruptObjectError):
            store.fetch(note.id)


# ---- 领域表：关系行赖以存在的那张表 ----


def test_custom_table_crud(tmp_path: Path) -> None:
    with _storage(tmp_path) as storage:
        kv = storage.table("kv", k="TEXT PRIMARY KEY", v="TEXT")
        kv.insert({"k": "a", "v": "1"})
        kv.upsert({"k": "a", "v": "2"})
        assert kv.select(k="a")[0]["v"] == "2"
        assert kv.count() == 1
        kv.update({"v": "3"}, k="a")
        assert kv.all()[0]["v"] == "3"
        kv.delete(k="a")
        assert kv.count() == 0


def test_upsert_preserves_unlisted_columns(tmp_path: Path) -> None:
    with _storage(tmp_path) as storage:
        table = storage.table("kv", id="TEXT PRIMARY KEY", a="TEXT", b="TEXT")
        table.insert({"id": "1", "a": "x", "b": "y"})
        table.upsert({"id": "1", "a": "z"})  # 未提供 b，应保留
        row = table.select(id="1")[0]
        assert row["a"] == "z"
        assert row["b"] == "y"


def test_table_none_predicate_and_arg_validation(tmp_path: Path) -> None:
    with _storage(tmp_path) as storage:
        table = storage.table("kv", id="TEXT PRIMARY KEY", note="TEXT")
        table.insert({"id": "1", "note": None})
        assert len(table.select(note=None)) == 1  # `= NULL` 会零命中，必须 IS NULL
        assert table.select(note="x") == []
        table.update({"note": "y"}, id="1")
        assert table.select(note=None) == []

        with pytest.raises(ValueError, match="至少一列"):
            table.insert({})
        with pytest.raises(ValueError, match="至少一列"):
            table.update({})
        with pytest.raises(ValueError, match="过滤条件"):
            table.update({"note": "z"})
        with pytest.raises(ValueError, match="过滤条件"):
            table.delete()


def test_create_table_rejects_bad_identifier(tmp_path: Path) -> None:
    with _storage(tmp_path) as storage:
        for name, columns in (
            ("bad name", {"id": "TEXT"}),
            ("ok", {"bad col": "TEXT"}),
        ):
            with pytest.raises(CairnError, match="非法"):
                create_table(storage.vault.index.conn, name, columns)


def test_create_table_rejects_bad_spec(tmp_path: Path) -> None:
    with _storage(tmp_path) as storage, pytest.raises(CairnError, match="列定义"):
        create_table(
            storage.vault.index.conn,
            "ok",
            {"id": "TEXT); DROP TABLE bucket; --"},
        )
