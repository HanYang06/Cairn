# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""块与载荷契约：默认值独立、身份分离、载荷可挂。"""

from __future__ import annotations

from core.storage.format.block import Block, Body
from core.storage.format.id import ID


def test_blocks_do_not_share_identity_or_body():
    """两块之间不得共用身份，也不得共用同一份载荷对象。"""
    first = Block[None]()
    second = Block[None]()

    assert first.id is not second.id
    assert first.id.value_uuid != second.id.value_uuid
    assert first.body is not second.body
    assert first.body.id.value_uuid != second.body.id.value_uuid


def test_bodies_do_not_share_identity():
    """两份载荷各有身份。"""
    assert Body().id.value_uuid != Body().id.value_uuid


def test_block_holds_payload():
    """块承载载荷：载荷结构不收窄，取回即原值。"""
    block = Block[int](body=Body[int](data=41, id=ID.of(b"41")))

    assert block.body.data == 41
    assert block.body.id.value_hash != ""
    assert block.id.value_hash == ""


def test_body_accepts_any_structure():
    """载荷可为字符串、列表、字典与二进制。"""
    assert Body[str](data="正文").data == "正文"
    assert Body[list[int]](data=[1, 2, 3]).data == [1, 2, 3]
    assert Body[dict[str, str]](data={"a": "b"}).data == {"a": "b"}
    assert Body[bytes](data=b"\x00\x01").data == b"\x00\x01"
