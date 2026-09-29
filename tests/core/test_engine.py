# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""存储引擎契约：两块记录的分辨、同内容只存一份、按身份读回、摘块与落盘后通知。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cbor2
import pytest

from core.event.bus import Bus
from core.event.catalog import OBJECT_DELETED, OBJECT_PUT
from core.exc import HubNotFoundError, ObjectNotFoundError
from core.storage.carrier import SlotRange
from core.storage.engine import Storage
from core.storage.format.block import body_addr_of, encode_block_payload
from core.storage.format.id import digest
from core.storage.index import Index
from core.storage.rows import Location
from core.storage.tables import Declaration, kernel_tables

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from core.event.events import Event


@pytest.fixture
def vault(tmp_path: Path) -> Iterator[tuple[Storage, Bus]]:
    """一个能落盘的引擎（库根 + 已对齐索引库 + 事件总线）。"""
    root = tmp_path / "vault"
    root.mkdir()
    with Index.open(root / "catalog.db", Declaration(kernel_tables()), create=True) as index:
        bus = Bus()
        yield Storage(index, root, bus=bus), bus


# ---- 载荷面：块记录与内容记录怎么分辨 ----


def test_block_payload_roundtrip():
    """指针编成载荷再取回来，值不变；同一份指针每次编出同一段字节（canonical）。"""
    assert body_addr_of(encode_block_payload("abc")) == "abc"
    assert encode_block_payload("a") == encode_block_payload("a")


def test_ordinary_bodies_are_never_mistaken_for_block_payloads():
    """保留键带不可打印前缀：业务正文里的普通键（哪怕叫 body_addr）不会被当成块载荷。"""
    assert body_addr_of(b"plain bytes") is None
    assert body_addr_of(cbor2.dumps({"body_addr": "x"})) is None
    assert body_addr_of(cbor2.dumps(["not", "a", "map"])) is None
    assert body_addr_of(b"") is None


# ---- 落盘与读回 ----


def test_store_then_load_roundtrip(vault: tuple[Storage, Bus]):
    """存进去、按块身份读回来，字节原样。"""
    engine, _bus = vault

    block = engine.store(b"hello", kind="notedata")

    assert engine.load(block.value_uuid) == b"hello"


def test_store_writes_two_rows_one_of_them_content(vault: tuple[Storage, Bus]):
    """一次 store 落两条记录：块行带类型标号，内容行的类型是空的（程序没给）。"""
    engine, _bus = vault

    block = engine.store(b"hello", kind="notedata")
    block_row = engine.locate(block.value_uuid)
    content_rows = engine.index.rows.locations_by_hash(digest(b"hello"))

    assert engine.index.rows.count_locations() == 2
    assert block_row is not None
    assert block_row.kind == "notedata"
    assert block_row.value_hash == digest(encode_block_payload(digest(b"hello")))
    assert len(content_rows) == 1
    assert content_rows[0].kind == ""
    assert content_rows[0].value_hash == digest(b"hello")


def test_same_content_is_stored_once(vault: tuple[Storage, Bus]):
    """同内容只存一份：第二块复用已有的内容记录，只多一块记录与一行。"""
    engine, _bus = vault

    first = engine.store(b"same", kind="notedata")
    second = engine.store(b"same", kind="notedata")

    assert first.value_uuid != second.value_uuid
    assert first.value_hash == second.value_hash
    assert len(engine.index.rows.locations_by_hash(digest(b"same"))) == 1
    assert engine.index.rows.count_locations() == 3
    assert engine.load(first.value_uuid) == b"same"
    assert engine.load(second.value_uuid) == b"same"


def test_content_identity_can_be_loaded_directly(vault: tuple[Storage, Bus]):
    """内容身份本身也能读回 body（它自己就是内容记录）。"""
    engine, _bus = vault
    engine.store(b"payload")

    content = engine.index.rows.locations_by_hash(digest(b"payload"))[0]

    assert engine.load(content.value_uuid) == b"payload"
    assert engine.body(digest(b"payload")) == b"payload"


def test_body_like_content_survives_a_roundtrip(vault: tuple[Storage, Bus]):
    """正文长得像块载荷也无妨：保留键带 NUL 前缀，业务数据占不到它。"""
    engine, _bus = vault
    tricky = cbor2.dumps({"body_addr": "x"})

    block = engine.store(tricky)

    assert engine.load(block.value_uuid) == tricky


def test_unknown_identity_is_reported(vault: tuple[Storage, Bus]):
    """没存过的东西：报"不在"，不返回空字节。"""
    engine, _bus = vault

    with pytest.raises(ObjectNotFoundError, match="索引"):
        engine.load("nope")
    with pytest.raises(ObjectNotFoundError, match="内容"):
        engine.body("0" * 64)


def test_body_refuses_a_row_pointing_at_the_wrong_bytes(vault: tuple[Storage, Bus]):
    """行指向的位置上不是那份内容：宁可报"内容不在"，也不把错的内容当成对的返回。"""
    engine, _bus = vault
    block = engine.store(b"other bytes")
    row = engine.locate(block.value_uuid)
    assert row is not None
    engine.index.rows.put_location(
        Location(
            value_uuid="liar",
            value_hash=digest(b"claimed"),
            hub=row.hub,
            pack=row.pack,
            span=row.span,
            size=row.size,
        )
    )

    with pytest.raises(ObjectNotFoundError, match="内容"):
        engine.body(digest(b"claimed"))


def test_engine_without_a_bus_still_works(tmp_path: Path):
    """不给总线也能跑：通知是可选件，不是依赖。"""
    root = tmp_path / "vault"
    root.mkdir()
    with Index.open(root / "catalog.db", Declaration(kernel_tables()), create=True) as index:
        engine = Storage(index, root)

        assert engine.default_hub == "main"
        block = engine.store(b"quiet")
        assert engine.load(block.value_uuid) == b"quiet"
        assert engine.drop(block.value_uuid) is True


# ---- 摘块 ----


def test_drop_removes_the_block_row_only(vault: tuple[Storage, Bus]):
    """摘块只摘块行：内容面不动（同内容可能还有别的块在用）。"""
    engine, _bus = vault
    block = engine.store(b"keep content", kind="notedata")
    address = digest(b"keep content")

    assert engine.drop(block.value_uuid) is True
    assert engine.drop(block.value_uuid) is False

    assert engine.locate(block.value_uuid) is None
    assert len(engine.index.rows.locations_by_hash(address)) == 1
    assert engine.body(address) == b"keep content"
    with pytest.raises(ObjectNotFoundError):
        engine.load(block.value_uuid)


# ---- 多 hub 与位置 ----


def test_store_into_a_named_hub_and_read_it_back(vault: tuple[Storage, Bus]):
    """写入按 hub 名分组、读取按行里的 hub 名开 hub。"""
    engine, _bus = vault

    block = engine.store(b"side data", hub="side")
    row = engine.locate(block.value_uuid)

    assert row is not None
    assert row.hub == "side"
    assert (engine.root / "side" / "packs").is_dir()
    assert engine.load(block.value_uuid) == b"side data"


def test_read_path_refuses_a_missing_hub_without_creating_it(vault: tuple[Storage, Bus]):
    """行指向一个不存在的 hub：报错，而且不会把它建出来。"""
    engine, _bus = vault
    engine.index.rows.put_location(
        Location(
            value_uuid="ghost",
            value_hash="h",
            hub="ghost",
            pack="p",
            span=SlotRange(first=0, last=0),
            size=1,
        )
    )

    with pytest.raises(HubNotFoundError):
        engine.load("ghost")

    assert not (engine.root / "ghost").exists()


# ---- 落盘后通知 ----


def test_events_are_emitted_after_the_write(vault: tuple[Storage, Bus]):
    """通知在落盘之后发：订阅者看到事件时，行已经在库里。"""
    engine, bus = vault
    seen: list[tuple[str, str, bool]] = []

    def handler(event: Event) -> None:
        row = engine.index.rows.location(event.subject)
        seen.append((event.type, event.subject, row is not None))

    bus.subscribe(OBJECT_PUT, handler)
    bus.subscribe(OBJECT_DELETED, handler)

    block = engine.store(b"notify", kind="notedata")
    engine.drop(block.value_uuid)

    assert seen == [
        (OBJECT_PUT, block.value_uuid, True),
        (OBJECT_DELETED, block.value_uuid, False),
    ]


def test_put_event_carries_body_address_and_kind(vault: tuple[Storage, Bus]):
    """`object.put` 的载荷里带 body 地址与类型标号。"""
    engine, bus = vault
    seen: list[Event] = []
    bus.subscribe(OBJECT_PUT, seen.append)

    block = engine.store(b"carry", kind="notedata")

    assert len(seen) == 1
    assert seen[0].source == "core.storage"
    assert seen[0].subject == block.value_uuid
    assert seen[0].data == {"body": digest(b"carry"), "kind": "notedata"}
