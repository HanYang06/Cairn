# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""块面：**一个块落成两条记录**（内容记录 ＋ 块记录），读回是"两条一拼"。

钉住五件事：

- 去重发生在**内容面**：同 body 的块各自一条块记录，body 只存一份；
- 两条记录各守记录层的自校验：`value_hash` 恒等于**本记录载荷**的摘要，
  body 的地址在块记录的**载荷**里（`body_addr`）——不在 ID 里；
- 判据来自载荷格式：载荷里带 `body_addr` 的才是块记录，故重建补回的块行照样认得出是块；
- 类型不进记录头：它落在索引库的 `kind` 列，不认识的类型降级读回；
- 索引缺行**报错**，而补行是巡检的事（`Vault.repair`）——两条路径各归各。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.storage import Block, BlockStore, Record, canonical
from core.storage.block import decode_canonical
from core.storage.blocks import BODY_POINTER_KEY
from core.types import CorruptObjectError, KindMismatchError, ObjectNotFoundError, ValueHash

if TYPE_CHECKING:
    from pathlib import Path


def _store(tmp_path: Path) -> BlockStore:
    return BlockStore.open(tmp_path / "vault")


def _block(body: bytes = b"", **kwargs: object) -> Block:
    return Block(body=body, **kwargs)  # type: ignore[arg-type]


def _body_addr(block: Block) -> str:
    """块的 body 地址：内容记录的身份是**编码后** body 的摘要（与去重键同源）。"""
    return str(ValueHash.of(block.encode_body()))


def _records_with_hash(store: BlockStore, digest: str) -> list[Record]:
    """盘上 `value_hash` 等于该地址的记录（内容记录的地址即它的载荷摘要）。"""
    return [record for _place, record in store.vault.records() if record.id.value_hash == digest]


def _block_record_of(store: BlockStore, oid: str) -> Record:
    """按身份取块记录。"""
    return store.vault.get(str(oid))


def test_store_then_fetch_roundtrip(tmp_path: Path) -> None:
    """一块进、一块出：身份、类型、属性、内容、时间与大小都对得上。"""
    with _store(tmp_path) as store:
        block = _block(b"hello cairn", type="blob", attrs={"title": "第一则", "tags": ["a"]})

        stored = store.store(block)

        assert stored.checksum == _body_addr(block)
        assert stored.size == len(b"hello cairn")
        assert stored.created > 0

        back = store.fetch(block.id)
        assert back.id == block.id
        assert back.type == "blob"
        assert back.attrs == {"title": "第一则", "tags": ["a"]}
        assert back.read() == b"hello cairn"
        assert back.verify()
        assert back.created == stored.created
        assert back.updated == stored.updated
        assert store.has(block.id)


def test_a_block_is_two_records(tmp_path: Path) -> None:
    """一个块 = 内容记录（载荷即内容）＋ 块记录（载荷带 body 地址与属性）。"""
    with _store(tmp_path) as store:
        block = _block(b"body bytes", type="blob", attrs={"title": "x"})
        store.store(block)
        digest = _body_addr(block)

        payloads = [record.payload for _place, record in store.vault.records()]
        assert payloads.count(block.encode_body()) == 1  # 内容记录：载荷就是编码后的 body

        blob = decode_canonical(_block_record_of(store, block.id).payload)
        assert blob[BODY_POINTER_KEY] == digest  # 指针在块记录的载荷里
        assert blob["attrs"] == {"title": "x"}
        # 只有内容记录那一行的 value_hash 等于 body 地址
        assert len(_records_with_hash(store, digest)) == 1


def test_each_record_keeps_the_record_layer_self_check(tmp_path: Path) -> None:
    """两条记录各自满足"身份 = 本记录载荷摘要"——指针不在 ID 里。"""
    with _store(tmp_path) as store:
        block = _block(b"self checking", type="blob", attrs={"title": "x"})
        store.store(block)

        for _place, record in store.vault.records():
            assert record.checksum == record.id.value_hash


def test_same_body_is_stored_once(tmp_path: Path) -> None:
    """同 body 的两个块：块记录各一条，body 只有一份（去重在内容面）。"""
    with _store(tmp_path) as store:
        one, two = _block(b"shared"), _block(b"shared")
        assert one.id != two.id
        store.store(one)
        store.store(two)

        bodies = [
            record.payload
            for _place, record in store.vault.records()
            if record.id.value_hash == _body_addr(one)
        ]
        assert bodies == [one.encode_body()]

        assert store.fetch(one.id).read() == b"shared"
        assert store.fetch(two.id).read() == b"shared"
        assert {item.id for item in store.iter_blocks()} == {one.id, two.id}


def test_only_block_records_carry_a_body_pointer(tmp_path: Path) -> None:
    """判据在载荷里：带 `body_addr` 的是块记录，内容记录没有这个字段。"""
    with _store(tmp_path) as store:
        block = _block(b"payload", type="blob")
        store.store(block)

        found = {
            str(row["value_uuid"]): str(row["kind"])
            for row in store.vault.index.find_by_hash(_body_addr(block))
        }
        # 按 body 地址找到的只有内容记录：它没有类型，也不是块的那个身份
        assert list(found.values()) == [""]
        assert block.id not in found

        blob = decode_canonical(_block_record_of(store, block.id).payload)
        assert BODY_POINTER_KEY in blob
        assert [item.id for item in store.iter_blocks()] == [block.id]  # 内容记录不算块


def test_unknown_type_is_read_back_as_a_bare_block(tmp_path: Path) -> None:
    """类型由程序给出（§3.5）：不认识就降级为裸块，不抛错、不丢弃。"""
    with _store(tmp_path) as store:
        block = _block(b"x", type="not-a-real-kind")
        store.store(block)

        back = store.fetch(block.id)

        assert type(back) is Block
        assert back.type == "not-a-real-kind"
        assert back.attrs == {}


def test_get_checks_the_type(tmp_path: Path) -> None:
    """按类型取回时类型不符即报错（口径与旧存储面一致）。"""
    with _store(tmp_path) as store:
        block = _block(b"x", type="blob")
        store.store(block)

        class Other(Block):
            """另一个类，用来触发类型不符。"""

        with pytest.raises(KindMismatchError):
            store.get(Other, block.id)
        assert store.get(Block, block.id).id == block.id


def test_fetch_of_an_unknown_id_raises(tmp_path: Path) -> None:
    with _store(tmp_path) as store, pytest.raises(ObjectNotFoundError):
        store.fetch("00000000000000000000000000")


def test_drop_removes_the_row_but_keeps_the_bytes(tmp_path: Path) -> None:
    """删块只摘定位行：字节留在载体里，等压实回收（物理坐标是投影）。"""
    with _store(tmp_path) as store:
        block = _block(b"keep the bytes", type="blob")
        store.store(block)
        before = len(list(store.vault.records()))

        assert store.drop(block.id) is True
        assert store.drop(block.id) is False  # 再删一次：本来就没有

        assert not store.has(block.id)
        with pytest.raises(ObjectNotFoundError):
            store.fetch(block.id)
        assert len(list(store.vault.records())) == before  # 字节一条没少


def test_missing_content_row_is_reported_and_repair_restores_it(tmp_path: Path) -> None:
    """索引缺行 → 读不出来（报损坏）；补行是巡检的事，补完照旧读得出来。"""
    with _store(tmp_path) as store:
        block = _block(b"recoverable", type="blob")
        store.store(block)
        digest = _body_addr(block)
        content_uuid = next(
            str(row["value_uuid"])
            for row in store.vault.index.find_by_hash(digest)
            if store.vault.get(str(row["value_uuid"])).checksum == digest
        )
        store.vault.index.remove_record(content_uuid)
        store.vault.index.commit()

        with pytest.raises(CorruptObjectError, match="内容缺失"):
            store.fetch(block.id)

        assert store.vault.patrol().counts() == {"missing_row": 1}
        assert len(store.vault.repair()) == 1

        assert store.fetch(block.id).read() == b"recoverable"


def test_a_body_that_looks_like_a_blob_is_not_taken_for_a_block(tmp_path: Path) -> None:
    """业务 body 长成"像块记录载荷"的样子也**不许**被当成块记录。

    判据用的是**保留键**（带不可打印前缀），业务数据占用不到；否则这种正文会让去重失效、
    并让 `iter_blocks` / `ids()` 整体报错——一条合法数据打断整份列举。
    """
    body = canonical({"body_addr": "ab" * 32})  # 一份"长得像"的正文
    with _store(tmp_path) as store:
        block = Block(body=body, type="blob")
        store.store(block)
        again = Block(body=body, type="blob")
        store.store(again)  # 同内容再去重：内容记录没被误判成块

        copies = [
            record
            for _place, record in store.vault.records()
            if record.id.value_hash == _body_addr(block)
        ]
        assert len(copies) == 1
        assert {item.id for item in store.iter_blocks()} == {block.id, again.id}


def test_repaired_block_rows_are_still_recognised_as_blocks(tmp_path: Path) -> None:
    """重建补回的块行类型为空，但**仍是块**：判据在载荷里，不在索引列里。

    这是"指针放载荷"换来的好处：档一重建（§8.5）不必先知道哪条行是块，
    也不怕把块记录与内容记录混成一样——顺扫读载荷即分得清。
    """
    with _store(tmp_path) as store:
        block = _block(b"recoverable", type="blob", attrs={"title": "t"})
        store.store(block)
        store.vault.index.remove_record(block.id)
        store.vault.index.commit()

        assert len(store.vault.repair()) == 1

        back = next(iter(store.iter_blocks()))
        assert back.id == block.id
        assert back.type == ""  # 类型不在记录头里，重建补不回来（降级读回，§3.3）
        assert back.attrs == {"title": "t"}
        assert back.read() == b"recoverable"


def test_empty_body_roundtrips(tmp_path: Path) -> None:
    """空 body 也要能读回来：去重键是全零长度的摘要，不是"没有内容"。"""
    with _store(tmp_path) as store:
        block = _block(b"", type="blob")
        store.store(block)

        assert store.fetch(block.id).read() == b""


def test_blocks_go_to_the_bucket_they_are_told(tmp_path: Path) -> None:
    """多桶对块面是透明的：只多一个"写进哪个桶"的参数。"""
    with _store(tmp_path) as store:
        left, right = _block(b"left", type="blob"), _block(b"right", type="blob")
        store.store(left, bucket="a")
        store.store(right, bucket="b")

        assert store.vault.placement(left.id) is not None
        assert store.vault.placement(left.id).bucket == "a"  # type: ignore[union-attr]
        assert store.vault.placement(right.id).bucket == "b"  # type: ignore[union-attr]
        assert store.fetch(left.id).read() == b"left"
        assert store.fetch(right.id).read() == b"right"
