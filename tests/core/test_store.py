# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from core.storage import (
    INDEX_TYPE,
    Block,
    Body,
    BodyField,
    Bucket,
    BucketConfig,
    canonical,
)
from core.types import CairnError, CorruptObjectError, ObjectNotFoundError
from core.types.attr import Attr, Data

if TYPE_CHECKING:
    from pathlib import Path


class Note(Block):
    """示例领域结构：继承块，重新描述 body，声明原生属性与关联业务表。"""

    type = "cairn.test.note"
    body = BodyField(factory=list)
    title = Attr()
    tags = Attr(factory=list)

    @classmethod
    def tables(cls) -> dict[str, dict[str, str]]:
        return {
            "notes": {"id": "TEXT PRIMARY KEY", "title": "TEXT"},
            "note_relations": {"src": "TEXT", "dst": "TEXT", "kind": "TEXT"},
        }


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


def _bucket(tmp_path: Path, **overrides: object) -> Bucket:
    return Bucket.create(tmp_path / "bucket", BucketConfig(**overrides))  # type: ignore[arg-type]


def test_body_default_and_edit() -> None:
    note = Note()
    assert note.body == []
    note.body.append("正文")
    assert note.body == ["正文"]


def test_body_hash_recomputes_after_in_place_edit() -> None:
    block = Block(body=ListBody([1]))
    before = block.body_hash()

    block.body.items.append(2)  # 就地改动，没人调 refresh()

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


def test_object_edit_roundtrip(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    note = bucket.new(Note)
    note.title = "Hello"
    note.body.append("正文")
    note.tags = {"a": None}
    returned = bucket.put(note)
    assert returned is note
    assert note.checksum

    loaded = bucket.get(Note, note.id)
    assert isinstance(loaded, Note)
    assert loaded.id == note.id
    assert loaded.title == "Hello"
    assert loaded.body == ["正文"]
    assert loaded.tags == {"a": None}


def test_id_is_locked() -> None:
    note = Note()
    with pytest.raises(AttributeError):
        note.id = "another-id"


def test_same_content_dedupes_physically(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    first = Note(body=["same"])
    second = Note(body=["same"])
    bucket.put(first)
    bucket.put(second)
    assert first.id != second.id
    assert bucket.catalog.count_blocks() == 2
    assert bucket.catalog.count_bodies() == 1


def test_unknown_type_falls_back_to_base(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    block = Block(type="cairn.test.unknown", body=["x"])
    bucket.put(block)
    loaded = bucket.get(Block, block.id)
    assert type(loaded) is Block
    assert loaded.type == "cairn.test.unknown"


def test_wrong_class_is_rejected(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    note = Note()
    bucket.put(note)
    with pytest.raises(CairnError):
        bucket.get(Project, note.id)


def test_body_pool_index_and_exists(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    first = Note(body=["same"])
    second = Note(body=["same"])
    other = Note(body=["different"])
    for block in (first, second, other):
        bucket.put(block)

    assert bucket.body_exists(first.body_hash())
    assert not bucket.body_exists("deadbeef")

    index = bucket.body_index
    assert len(index[first.body_hash()]) == 2
    assert index[other.body_hash()] == [other.id]


def test_chunked_content_roundtrip(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path, block_max_bytes=16)
    data = bytes(range(64))
    root = bucket.put_content(data, kind="image")
    block = bucket.get(Block, root)
    assert block.type == INDEX_TYPE
    assert len(block.body) == 4
    assert bucket.read_content(root) == data


def test_small_content_is_one_block(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path, block_max_bytes=1024)
    root = bucket.put_content(b"tiny", kind="image")
    assert bucket.get(Block, root).type == "image"
    assert bucket.read_content(root) == b"tiny"


def test_pack_seals_and_rolls_over(tmp_path: Path) -> None:
    # 封口只看字节线（块数不再是旋钮）：上限压到 1 字节，每写一块就换一个载体。
    bucket = _bucket(tmp_path, pack_max_bytes=1, block_max_bytes=1024)
    ids = [bucket.put(Block(type="test.note", body=[str(i)])).id for i in range(3)]
    assert bucket.catalog.count_packs() == 3
    for block_id in ids:
        assert bucket.get(Block, block_id).id == block_id


def test_persistence_across_reopen(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    note = bucket.new(Note)
    note.body.append("persist")
    bucket.put(note)
    bucket.close()

    reopened = Bucket.open(tmp_path / "bucket")
    loaded = reopened.get(Note, note.id)
    assert isinstance(loaded, Note)
    assert loaded.body == ["persist"]


def test_config_persists_across_reopen(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path, block_max_bytes=32, pack_max_bytes=4096)
    bucket.close()
    reopened = Bucket.open(tmp_path / "bucket")
    assert reopened.config.block_max_bytes == 32
    assert reopened.config.pack_max_bytes == 4096


def test_delete_removes_object(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    note = Note()
    bucket.put(note)
    assert bucket.delete(note.id) is True
    with pytest.raises(ObjectNotFoundError):
        bucket.get(Note, note.id)
    assert bucket.delete(note.id) is False


def test_corruption_is_detected(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    note = Note(body=["good"])
    bucket.put(note)
    checksum = bucket.catalog.block_body_id(note.id)
    assert checksum is not None
    location = bucket.catalog.find_body(checksum)
    assert location is not None
    path = bucket.packs_dir / bucket.catalog.pack_name(location.pack_id)
    with path.open("r+b") as handle:
        handle.seek(location.offset)
        handle.write(b"\xff")
    with pytest.raises(CorruptObjectError):
        bucket.get(Note, note.id)


def test_decode_rebuilds_subclass(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    note = Note(body=["x"])
    note.title = "T"
    bucket.put(note)
    decoded = bucket.get(Block, note.id)
    assert isinstance(decoded, Note)
    assert decoded.title == "T"


def test_validation_runs_on_put(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    with pytest.raises(ValueError, match="缺少 ok"):
        bucket.put(Strict())
    good = Strict(attrs={"ok": True})
    bucket.put(good)
    assert bucket.get(Strict, good.id).attrs == {"ok": True}


def test_author_persists(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    note = Note(body=["x"])
    note.author = "韩"
    bucket.put(note)
    assert bucket.get(Note, note.id).author == "韩"


def test_block_metadata_fields(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    note = bucket.new(Note)
    note.body.append("v1")
    bucket.put(note)
    assert note.created > 0
    assert note.updated > 0
    assert note.size > 0


def test_fields_and_config_persist(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    note = bucket.new(Note)
    note.title = "T"
    note.body.append("x")
    note.config["isolated"] = False
    bucket.put(note)

    loaded = bucket.get(Note, note.id)
    assert loaded.size == note.size
    assert loaded.created == note.created
    assert loaded.updated == note.updated
    assert loaded.config == {"isolated": False}


def test_transaction_rolls_back(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    note = bucket.new(Note)

    def boom() -> None:
        with bucket.transaction():
            bucket.put(note)
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        boom()
    assert bucket.has(note.id) is False


def test_transaction_commits(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    note = bucket.new(Note)
    with bucket.transaction():
        bucket.put(note)
    assert bucket.has(note.id) is True


def test_custom_table_crud(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    kv = bucket.table("kv", k="TEXT PRIMARY KEY", v="TEXT")
    kv.insert({"k": "a", "v": "1"})
    kv.upsert({"k": "a", "v": "2"})
    assert kv.select(k="a")[0]["v"] == "2"
    assert kv.count() == 1
    kv.update({"v": "3"}, k="a")
    assert kv.all()[0]["v"] == "3"
    kv.delete(k="a")
    assert kv.count() == 0


def test_mount_builds_domain_tables(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    bucket.mount(Note)
    notes = bucket.table("notes")
    note = bucket.new(Note)
    note.title = "T"
    bucket.put(note)
    notes.upsert({"id": note.id, "title": note.title})
    rows = notes.select(id=note.id)
    assert rows[0]["title"] == "T"
    relations = bucket.table("note_relations")
    relations.insert({"src": note.id, "dst": "other", "kind": "ref"})
    assert relations.count() == 1


def test_put_auto_mounts_domain_tables(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    bucket.put(bucket.new(Note))  # 首次写入即触发 Note.bind
    names = {
        row["name"] for row in bucket.query("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"notes", "note_relations"} <= names


def test_isolated_config_gets_own_pack(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    note = bucket.new(Note)
    note.config["isolated"] = True
    bucket.put(note)
    assert bucket.catalog.count_packs() == 1

    other = bucket.new(Note)
    other.body.append("x")
    bucket.put(other)
    assert bucket.catalog.count_packs() == 2


def test_newer_catalog_version_fails_closed(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    bucket.catalog.set_meta("catalog_version", "999")
    bucket.catalog.commit()
    bucket.close()
    with pytest.raises(CairnError, match="目录版本过新"):
        Bucket.open(tmp_path / "bucket")


def test_corrupt_block_metadata_is_reported(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    note = Note(body=["x"])
    bucket.put(note)
    # 元数据本应是 CBOR 映射；写成数组即损坏
    bucket.execute("UPDATE block SET data = ? WHERE oid = ?", (canonical([1, 2, 3]), note.id))
    with pytest.raises(CorruptObjectError, match="元数据非法"):
        bucket.get(Note, note.id)


def test_transaction_rollback_reverts_pack_bytes(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    note = bucket.new(Note)

    def boom() -> None:
        with bucket.transaction():
            note.body.append("rolled")
            bucket.put(note)
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        boom()
    size = sum(path.stat().st_size for path in bucket.packs_dir.iterdir())
    assert size == 0
    assert bucket.catalog.count_bodies() == 0
    assert bucket.catalog.count_packs() == 0


def test_upsert_preserves_unlisted_columns(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    table = bucket.table("kv", id="TEXT PRIMARY KEY", a="TEXT", b="TEXT")
    table.insert({"id": "1", "a": "x", "b": "y"})
    table.upsert({"id": "1", "a": "z"})  # 未提供 b，应保留
    row = table.select(id="1")[0]
    assert row["a"] == "z"
    assert row["b"] == "y"


def test_table_none_predicate_and_arg_validation(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    table = bucket.table("kv", id="TEXT PRIMARY KEY", note="TEXT")
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


def test_block_decode_requires_id() -> None:
    with pytest.raises(CorruptObjectError):
        Block.decode(b"")


def test_corrupt_bucket_config_fails_closed(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    bucket.catalog.set_meta("config", "{not json")
    bucket.catalog.commit()
    bucket.close()
    with pytest.raises(CairnError, match="配置损坏"):
        Bucket.open(tmp_path / "bucket")


def test_create_table_rejects_bad_identifier(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    with pytest.raises(CairnError):
        bucket.catalog.create_table("bad name", {"id": "TEXT"})
    with pytest.raises(CairnError):
        bucket.catalog.create_table("ok", {"bad col": "TEXT"})


def test_create_table_rejects_bad_spec(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    with pytest.raises(CairnError, match="列定义"):
        bucket.catalog.create_table("ok", {"id": "TEXT); DROP TABLE block; --"})


def test_iter_block_ids_streams(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    bucket.put(Note(body=["x"]))
    ids = bucket.iter_block_ids()
    assert iter(ids) is ids  # 生成器：不整表物化
    assert list(ids)


def test_nested_transaction_inner_failure_rolls_back(tmp_path: Path) -> None:
    bucket = _bucket(tmp_path)
    note = bucket.new(Note)

    def inner() -> None:
        with bucket.transaction():
            bucket.put(bucket.new(Note))
            raise RuntimeError("inner")

    with bucket.transaction():
        note.body.append("outer")
        bucket.put(note)
        with pytest.raises(RuntimeError, match="inner"):
            inner()

    assert bucket.has(note.id) is False  # 内层失败过 → 外层整体回滚


def test_data_annotation_becomes_data_field() -> None:
    class Holder(Block):
        type = "test.holder.data"
        items: Data[list[str]] = []  # noqa: RUF012 — 测试声明，验证注解路由

    assert isinstance(Holder.__dict__["items"], Data)
