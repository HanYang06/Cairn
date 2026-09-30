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
from core.storage.engine import Storage
from core.storage.format.block import BodyRef, body_ref_of, encode_block_payload
from core.storage.format.id import digest
from core.storage.index import Index
from core.storage.rows import BlockRow, BodyRow
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


def _stray_block(value_uuid: str, *, hub: str = "main", pack: str = "p") -> BlockRow:
    """造一条指向某处的块行（测试用：位置是编的，只为让读路径去找它）。"""
    return BlockRow(
        name="",
        value_uuid=value_uuid,
        value_hash="h",
        birth_time=0,
        in_hub=hub,
        in_hub_pack=pack,
        in_pack_slot=(0, 0),
        body_value_uuid="bu",
        body_value_hash="bh",
    )


# ---- 载荷面：块记录与内容记录怎么分辨 ----


def test_block_payload_roundtrip():
    """指针编成载荷再取回来，两套凭证都在；同一份指针每次编出同一段字节（canonical）。"""
    ref = BodyRef(value_uuid="u1", value_hash="a" * 64)

    assert body_ref_of(encode_block_payload(ref)) == ref
    assert encode_block_payload(ref) == encode_block_payload(
        BodyRef(value_uuid="u1", value_hash="a" * 64)
    )


def test_ordinary_bodies_are_never_mistaken_for_block_payloads():
    """保留键带不可打印前缀：业务正文里的普通键（哪怕叫 body_ref）不会被当成块载荷。"""
    assert body_ref_of(b"plain bytes") is None
    assert body_ref_of(cbor2.dumps({"body_ref": "x"})) is None
    assert body_ref_of(cbor2.dumps({"body_addr": "x"})) is None
    assert body_ref_of(cbor2.dumps(["not", "a", "map"])) is None
    assert body_ref_of(b"") is None


def test_a_pointer_with_only_half_the_credentials_is_not_a_block_payload():
    """只带一半凭证的映射不算块载荷：宁可当内容读，也不假装指针成立。"""
    from core.storage.format.block import BODY_REF_KEY  # noqa: PLC0415

    half = cbor2.dumps({BODY_REF_KEY: {"value_hash": "a" * 64}})

    assert body_ref_of(half) is None


# ---- 落盘与读回 ----


def test_store_then_load_roundtrip(vault: tuple[Storage, Bus]):
    """存进去、按块身份读回来，字节原样。"""
    engine, _bus = vault

    block = engine.store(b"hello", kind="notedata")

    assert engine.load(block.value_uuid) == b"hello"


def test_store_writes_two_records_in_two_tables(vault: tuple[Storage, Bus]):
    """一次 store 落两条记录：块行进 `block`（带类型标号），内容行进 `body`（无类型）。"""
    engine, _bus = vault

    block = engine.store(b"hello", kind="notedata")
    block_row = engine.locate(block.value_uuid)
    body_rows = engine.index.rows.bodies_by_hash(digest(b"hello"))

    assert engine.index.rows.count_blocks() == 1
    assert engine.index.rows.count_bodies() == 1
    assert block_row is not None
    assert block_row.kind == "notedata"
    body_uuid, body_hash = _body_of(engine, b"hello")
    pointer = BodyRef(value_uuid=body_uuid, value_hash=body_hash)
    assert block_row.value_hash == digest(encode_block_payload(pointer))
    assert len(body_rows) == 1
    assert body_rows[0].value_hash == digest(b"hello")


def _body_of(engine: Storage, data: bytes) -> tuple[str, str]:
    """取某份内容那一行的两套凭证（断言里要拼指针时用）。"""
    row = engine.index.rows.bodies_by_hash(digest(data))[0]
    return row.value_uuid, row.value_hash


def test_same_content_is_stored_once(vault: tuple[Storage, Bus]):
    """同内容只存一份：第二块复用已有内容行，只多一条块记录与一行。"""
    engine, _bus = vault

    first = engine.store(b"same", kind="notedata")
    second = engine.store(b"same", kind="notedata")

    assert first.value_uuid != second.value_uuid
    assert first.value_hash == second.value_hash
    assert len(engine.index.rows.bodies_by_hash(digest(b"same"))) == 1
    assert engine.index.rows.count_blocks() == 2
    assert engine.index.rows.count_bodies() == 1
    assert engine.load(first.value_uuid) == b"same"
    assert engine.load(second.value_uuid) == b"same"


def test_both_blocks_point_at_the_same_body(vault: tuple[Storage, Bus]):
    """同内容的两块，指针指向**同一个 body 身份**（指针落成两列，故这件事查得到）。"""
    engine, _bus = vault

    first = engine.store(b"shared", kind="notedata")
    second = engine.store(b"shared", kind="notedata")
    address = digest(b"shared")

    assert {row.value_uuid for row in engine.index.rows.blocks_by_body(address)} == {
        first.value_uuid,
        second.value_uuid,
    }
    first_row = engine.locate(first.value_uuid)
    second_row = engine.locate(second.value_uuid)
    assert first_row is not None
    assert second_row is not None
    assert first_row.body_value_uuid == second_row.body_value_uuid


def test_content_identity_can_be_loaded_directly(vault: tuple[Storage, Bus]):
    """内容身份本身也能读回 body（它自己就是那条内容记录）。"""
    engine, _bus = vault
    engine.store(b"payload")

    content = engine.index.rows.bodies_by_hash(digest(b"payload"))[0]

    assert engine.load(content.value_uuid) == b"payload"
    assert engine.body(digest(b"payload")) == b"payload"


def test_body_like_content_survives_a_roundtrip(vault: tuple[Storage, Bus]):
    """正文长得像块载荷也无妨：保留键带 NUL 前缀，业务数据占不到它。"""
    engine, _bus = vault
    tricky = cbor2.dumps({"body_ref": "x"})

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
    row = engine.store(b"other bytes")
    block_row = engine.locate(row.value_uuid)
    assert block_row is not None
    engine.index.rows.put_body(
        BodyRow(
            name="",
            value_uuid="liar",
            value_hash=digest(b"claimed"),
            birth_time=0,
            in_hub=block_row.in_hub,
            in_hub_pack=block_row.in_hub_pack,
            in_pack_slot=block_row.in_pack_slot,
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
    assert len(engine.index.rows.bodies_by_hash(address)) == 1
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
    assert row.in_hub == "side"
    assert (engine.root / "side" / "packs").is_dir()
    assert engine.load(block.value_uuid) == b"side data"


def test_read_path_refuses_a_missing_hub_without_creating_it(vault: tuple[Storage, Bus]):
    """内容行指向一个不存在的 hub：读内容即报错，而且不会把它建出来。"""
    engine, _bus = vault
    address = digest(b"elsewhere")
    engine.index.rows.put_body(
        BodyRow(
            name="",
            value_uuid="ghost",
            value_hash=address,
            birth_time=0,
            in_hub="ghost",
            in_hub_pack="p",
            in_pack_slot=(0, 0),
        )
    )

    with pytest.raises(HubNotFoundError):
        engine.body(address)

    assert not (engine.root / "ghost").exists()


# ---- 落盘后通知 ----


def test_events_are_emitted_after_the_write(vault: tuple[Storage, Bus]):
    """通知在落盘之后发：订阅者看到事件时，行已经在库里。"""
    engine, bus = vault
    seen: list[tuple[str, str, bool]] = []

    def handler(event: Event) -> None:
        row = engine.index.rows.block(event.subject)
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
