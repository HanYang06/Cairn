# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""类型级声明契约：类体里那组 `__…__` 怎么进登记、怎么流进表声明、怎么被淘汰掉。

与 `test_tablegen.py` 的分工：那一支钉"类型 → 表"这条链；这一支钉**存储行为**这一层
（归属、配额、体积上限）。后者**不进声明文件**——流进去的只有档位与归属。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from core.exc import TableDeclarationError
from core.storage import tablegen
from core.storage.format.block import Block, Body, register_type
from core.storage.registry import REGISTRY, OverBudget, Tier, TypeDecl
from core.storage.tables import load_tables

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_KIB = 1024


def _decl(name: str) -> TypeDecl:
    """取一个已登记的声明；没登记就当场失败。"""
    decl = REGISTRY.get(name)
    assert decl is not None, name
    return decl


@pytest.fixture(autouse=True)
def clean_registry() -> Iterator[None]:
    """每个用例一份干净的登记，**用完还原**（与 `test_attr.py` 同一套）。"""
    REGISTRY.clear()
    register_type(Body)
    register_type(Block)
    yield
    REGISTRY.clear()
    register_type(Body)
    register_type(Block)


# ---- 声明进登记 ----


def test_declared_storage_fields_land_in_the_declaration():
    """类体里那组 `__…__` 各有其位：归属、档位、配额、体积上限。"""

    @dataclass(slots=True)
    class AttrIndex(Block[None]):
        """测试用的块。"""

        __table__ = "attrindex"
        __owner__ = "note"
        __tier__ = Tier.SOURCE
        __backup__ = True
        __hub__ = "idx"
        __slot_budget__ = 64
        __pack_budget__ = 4
        __over_budget__ = OverBudget.DENY
        __max_block_mbyte__ = 1

    decl = _decl("AttrIndex")

    assert decl.owner == "note"
    assert decl.tier is Tier.SOURCE
    assert decl.backup is True
    assert decl.hub == "idx"
    assert decl.slot_budget == 64
    assert decl.pack_budget == 4
    assert decl.over_budget is OverBudget.DENY
    assert decl.max_block_bytes == 1 * _KIB**2


def test_storage_fields_default_to_the_quiet_choices():
    """一档都不写时的默认：可重建、不独占、无配额、静默续份。"""

    @dataclass(slots=True)
    class Plain(Block[None]):
        """最朴素的测试类型。"""

    decl = _decl("Plain")

    assert decl.tier is Tier.DERIVED
    assert decl.backup is False
    assert decl.own_hub is False
    assert decl.hub == ""
    assert decl.slot_budget is None
    assert decl.pack_budget is None
    assert decl.max_block_bytes is None
    assert decl.over_budget is OverBudget.EXTEND


def test_own_hub_and_hub_cannot_both_be_given():
    """独占与指定是两回事，同时给就没有答案，登记期报错。"""
    with pytest.raises(TableDeclarationError, match="互斥"):

        @dataclass(slots=True)
        class Both(Block[None]):
            """同时声明独占与指定的测试类型。"""

            __own_hub__ = True
            __hub__ = "idx"


def test_non_positive_budget_is_rejected():
    """配额写成零等于"一开始就没有"，那是没写，不是配额，故当场报错。"""
    with pytest.raises(TableDeclarationError, match="必须为正"):

        @dataclass(slots=True)
        class Zero(Block[None]):
            """配额写成零的测试类型。"""

            __pack_budget__ = 0


def test_non_integer_budget_is_rejected():
    """配额只收整数：字符串不会静默变成数字。"""
    with pytest.raises(TableDeclarationError, match="必须是整数"):

        @dataclass(slots=True)
        class Text(Block[None]):
            """配额写成字符串的测试类型。"""

            __pack_budget__ = "4"


# ---- 体积上限：分档归一 ----


def test_max_block_units_add_up_and_normalise():
    """分档相加归一成**字节数**：只写一档就是它，四档都写就是它们的和。"""

    @dataclass(slots=True)
    class One(Block[None]):
        """只写一档的测试类型。"""

        __max_block_mbyte__ = 1

    @dataclass(slots=True)
    class All(Block[None]):
        """四档都写的测试类型。"""

        __max_block_byte__ = 8
        __max_block_kbyte__ = 1
        __max_block_mbyte__ = 1
        __max_block_gbyte__ = 1

    assert _decl("One").max_block_bytes == 1 * _KIB**2
    assert _decl("All").max_block_bytes == 8 + 1 * _KIB + 1 * _KIB**2 + 1 * _KIB**3


# ---- 流进表声明 ----


def test_table_spec_takes_tier_and_owner_from_the_declaration():
    """档位与归属流进表声明；真源档不写重建来源（写反了构造校验会拦）。"""

    @dataclass(slots=True)
    class Owned(Block[None]):
        """带归属、声明为真源档的测试类型。"""

        __owner__ = "note"
        __tier__ = Tier.SOURCE

    spec = tablegen.table_spec(_decl("Owned"))

    assert spec.owner == "note"
    assert spec.tier is Tier.SOURCE
    assert spec.rebuild_from == ""


def test_derived_tier_still_writes_its_rebuild_source():
    """可重建那一档必须写明来路——这条旧行为不因新字段而丢。"""

    @dataclass(slots=True)
    class Rebuildable(Block[None]):
        """可重建档的测试类型。"""

    spec = tablegen.table_spec(_decl("Rebuildable"))

    assert spec.tier is Tier.DERIVED
    assert spec.rebuild_from


# ---- 声明文件的淘汰出口 ----


def test_sync_prunes_named_columns_and_leaves_the_rest(tmp_path: Path):
    """淘汰列要**显式点名**：点到的从文件里去掉，没点到的照旧。"""
    file = tmp_path / "tables.yaml"
    tablegen.sync(file)

    report = tablegen.sync(file, prune_columns={"block": ["kind"]})
    tables = {table.name: table for table in load_tables(file)}

    assert "淘汰列: block.kind" in report
    assert tables["block"].column("kind") is None
    assert tables["block"].column("value_uuid") is not None, "没点名的列一个字不动"


def test_pruning_an_absent_column_is_a_no_op(tmp_path: Path):
    """点名的列本来就不在时是空操作：不报错，也不写一遍文件。"""
    file = tmp_path / "tables.yaml"
    tablegen.sync(file)
    before = file.read_text(encoding="utf-8")

    report = tablegen.sync(file, prune_columns={"block": ["没有这一列"]})

    assert report == ()
    assert file.read_text(encoding="utf-8") == before


def test_pruning_a_primary_key_column_is_refused(tmp_path: Path):
    """把主键列删了，表就立不起来——当场报错，不写出一份坏声明。"""
    file = tmp_path / "tables.yaml"
    tablegen.sync(file)

    with pytest.raises(TableDeclarationError):
        tablegen.sync(file, prune_columns={"block": ["value_uuid"]})
