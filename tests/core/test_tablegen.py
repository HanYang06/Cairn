# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""类型反查契约：定义类型就登记、登记就推出表形状、表形状写进声明文件再由它建库。

这一组用例钉住的是"表会自己诞生"这条链的每一段：
**类型定义 → 登记表 → 表声明 → 声明文件 → 库**。任何一段断开，本文件都会红。

登记是**进程内**的，故每个用例自带一份干净的登记：内核那两张表按定义处的形状重放，
用例自己定义的类型则在用例里诞生、随用例结束消失。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from core.exc import TableDeclarationError
from core.storage import tablegen
from core.storage.format.block import Block, Body, register_type
from core.storage.format.id import ID_FIELDS
from core.storage.index import Index
from core.storage.registry import REGISTRY, TypeDecl
from core.storage.tables import Declaration, kernel_tables, load_tables

if TYPE_CHECKING:
    from pathlib import Path

#: `id: ID` 那个字段落成的整整一套身份列 = `ID` 的全部字段。
_IDENTITY = ID_FIELDS


def _registered(name: str) -> TypeDecl:
    """取一个已登记的类型；没登记就当场失败（用例要的是它一定在）。"""
    decl = REGISTRY.get(name)
    assert decl is not None, name
    return decl


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    """每个用例一份干净的登记：内核那两张表按定义处的形状重放。"""
    REGISTRY.clear()
    register_type(Body)
    register_type(Block)


# ---- 反查：谁用了 ID ----

# 类定义时 `__init_subclass__` 就会跑，故这里定义完，登记表里就该有它。


def test_defining_a_type_registers_itself():
    """类型定义即登记：名字、表名与它持有的 ID 字段都记下来了。"""

    @dataclass(slots=True)
    class Notedata(Block[str]):
        """测试用的领域类型：它一被定义，`notedata` 那张表就诞生了。"""

        title: str = ""

    decl = _registered("Notedata")

    assert decl is not None
    assert decl.table == "notedata"
    assert decl.ids == _IDENTITY
    assert decl.refs == {"body": "body"}, "块持有的 body 字段就是指向 body 表的指针"
    assert decl.doc == "测试用的领域类型：它一被定义，`notedata` 那张表就诞生了。"


def test_a_subclass_gets_its_own_table_instead_of_inheriting_the_parent_name():
    """继承不等于共用表：子类没写 `__table__` 就按类名推，绝不顶掉父类那张表。"""

    @dataclass(slots=True)
    class Plain(Body[int]):
        """不带表的覆盖：表名由类名给出。"""

    assert REGISTRY.get("Plain") is not None
    assert REGISTRY.table("plain") is not None
    assert _registered("Body").table == "body", "父类那张表还在"


def test_an_explicit_table_name_wins():
    """本类自己写下 `__table__` 时以它为准（继承来的不算）。"""

    @dataclass(slots=True)
    class Curated(Block[str]):
        """显式指定表名。"""

        __table__ = "curated_table"

    decl = _registered("Curated")

    assert decl is not None
    assert decl.table == "curated_table"


def test_the_two_kernel_types_are_registered_by_their_own_definitions():
    """`Body` / `Block` 两张内核表也是定义出来的，不是手写的。"""
    body = REGISTRY.table("body")
    block = REGISTRY.table("block")

    assert body is not None
    assert body.name == "Body"
    assert body.refs == {}
    assert block is not None
    assert block.refs == {"body": "body"}


def test_registration_rejects_a_duplicate_name_with_a_different_shape():
    """同名但形状不同即报错：两处写同一张表就是两处事实。"""
    with pytest.raises(TableDeclarationError, match="形状与上次不同"):
        REGISTRY.register(TypeDecl(name="Body", table="body2"))


def test_registration_rejects_a_duplicate_table_name():
    """表名被别的类型占着也不行：一张表一个类型。"""
    with pytest.raises(TableDeclarationError, match="已经由类型"):
        REGISTRY.register(TypeDecl(name="OtherName", table="body"))


def test_re_registering_the_same_shape_is_a_replay():
    """同一个类被登记两次（`slots=True` 会重建类）算重放，不算冲突。"""
    assert register_type(Body) == _registered("Body")
    assert register_type(Block) == _registered("Block")


def test_registration_rejects_an_unbindable_field():
    """登记的只能是 `ID` 的字段：别处来的名字绑不成列（设计篇 §3.5）。"""
    with pytest.raises(TableDeclarationError, match="绑不成"):
        TypeDecl(name="X", table="x", ids=("value_uuid", "checksum"))


def test_registration_requires_the_key_field():
    """没有 `value_uuid` 就没有主键，这种登记要拦下。"""
    with pytest.raises(TableDeclarationError, match="必须登记 value_uuid"):
        TypeDecl(name="X", table="x", ids=("value_hash",))


def test_registration_rejects_a_ref_without_a_target():
    """引用必须说清指向哪张表。"""
    with pytest.raises(TableDeclarationError, match="指向哪张表"):
        TypeDecl(name="X", table="x", refs={"body": ""})


# ---- 表形状：登记算出列与主键 ----


def test_a_registered_type_gets_a_table_of_the_id_fields_pointer_and_kind():
    """一个类型的表 = `ID` 的全部字段 ＋（指针两列）＋ 类型标号：行是 ID 的镜像。"""
    spec = tablegen.table_spec(_registered("Block"))

    assert spec.name == "block"
    assert spec.primary_key == ("value_uuid",)
    assert spec.column_names() == (
        "name",
        "value_uuid",
        "value_hash",
        "birth_time",
        "in_hub",
        "in_hub_pack",
        "in_pack_slot",
        "body_value_uuid",
        "body_value_hash",
        "kind",
    )


def test_the_body_table_has_no_kind_column():
    """内容记录没有类型标号：程序不写它，`body` 表就不该有这一列。"""
    spec = tablegen.table_spec(_registered("Body"))

    assert spec.column("kind") is None
    assert spec.column("body_value_uuid") is None


def test_bound_columns_have_no_type_or_doc_in_the_declaration():
    """绑定列的类型随 `ID` 的字段走，声明里不写第二份。"""
    spec = tablegen.table_spec(_registered("Block"))
    column = spec.column("value_uuid")

    assert column is not None
    assert column.doc == ""
    assert column.source.value == "identity"


def test_reference_columns_carry_the_body_prefix():
    """指向别处的两列带前缀，免得同一张表里两个 ID 的同名字段撞名。"""
    spec = tablegen.table_spec(_registered("Block"))
    names = [column.sql_name for column in spec.columns]

    assert {"body_value_uuid", "body_value_hash"} <= set(names)
    assert len(names) == len(set(names)), "列名不许撞"


def test_only_the_three_optional_id_fields_may_be_empty():
    """可空的只有"未绑定内容"那三个字段：位置段没有值，那一行就没有意义。"""
    spec = tablegen.table_spec(_registered("Body"))
    nullable = {column.sql_name for column in spec.columns if not column.not_null}

    assert nullable == {"value_hash", "birth_time", "name"}


def test_a_dangling_reference_is_refused():
    """引用指向没登记的表：那是断链，不许带进库。"""
    registry = type(REGISTRY)()
    registry.register(TypeDecl(name="Lonely", table="lonely", refs={"body": "nobody"}))

    with pytest.raises(TableDeclarationError, match="没登记的表"):
        tablegen.type_tables(registry)


# ---- 声明文件：只追加、不覆写 ----


def test_generating_a_file_from_nothing(tmp_path: Path):
    """文件不在 → 整份生成：声明文件由此诞生，且带 SPDX 头与"由代码写出"的说明。"""
    target = tmp_path / "tables.yaml"

    changed = tablegen.sync(target, replace=("record",))

    assert changed, "新建的表要能在报告里看见"
    text = target.read_text(encoding="utf-8")
    assert text.startswith("# SPDX-FileCopyrightText: 2026 HanYang06")
    assert "这份文件由代码写出来" in text

    names = [table.name for table in load_tables(target)]
    assert names == ["block", "body", "hub"]


def test_a_registered_type_is_written_into_the_file(tmp_path: Path):
    """登记表里有、文件里没有的那张表会被补进文件（这就是"表自己诞生"）。"""
    target = tmp_path / "tables.yaml"
    tablegen.sync(target)
    before = target.read_text(encoding="utf-8")

    @dataclass(slots=True)
    class Fresh(Block[str]):
        """刚定义的领域类型：它一诞生，下一轮就多一张表。"""

    tablegen.sync(target)

    after = target.read_text(encoding="utf-8")
    assert before in after, "旧内容一个字都不许动"
    assert "- name: fresh" in after


def test_hand_written_content_is_never_clobbered(tmp_path: Path):
    """人写的东西留着：已存在的表不被重写，人手加的列也不被删。"""
    target = tmp_path / "tables.yaml"
    tablegen.sync(target)
    text = target.read_text(encoding="utf-8")
    hand = text.replace(
        "    - id().value_uuid\n",
        "    - id().value_uuid\n    # 人手加的一列，引擎不许动它\n"
        "    - { name: mine, from: prog, type: text, doc: 我自己加的 }\n",
        1,
    )
    target.write_text(hand, encoding="utf-8")

    tablegen.sync(target)

    assert target.read_text(encoding="utf-8") == hand


def test_tables_are_separated_by_a_blank_line(tmp_path: Path):
    """**排版也是契约**：文件头与第一张表之间、每两张表之间都空一行。

    这份文件要给人看、给人改，表与表贴成一摞读起来费力。空行不进解析口，
    故它可以只管观感——但正因为它只靠观感维持，才需要一条用例钉住。
    """
    target = tmp_path / "tables.yaml"
    tablegen.sync(target)

    text = target.read_text(encoding="utf-8")
    blocks = text.split("\n\n")

    assert blocks[0].startswith("# SPDX-FileCopyrightText"), "第一段是文件头"
    assert all(block.startswith("- name: ") for block in blocks[1:]), "其后每段一张表"
    assert len(blocks) == 4, "三张内核表加文件头"
    assert "\n\n\n" not in text, "不许多空一行"


def test_the_dropped_note_only_appears_when_something_was_dropped(tmp_path: Path):
    """那句"淘汰了某某"只在真淘汰过时才写：空操作不该在文件里留一句旧话。"""
    target = tmp_path / "tables.yaml"
    tablegen.sync(target)

    assert "淘汰" not in target.read_text(encoding="utf-8")

    target.write_text(
        "- name: record\n"
        "  tier: derived\n"
        "  rebuild_from: 载体\n"
        "  columns: [id().value_uuid]\n"
        "  primary_key: [value_uuid]\n",
        encoding="utf-8",
    )
    tablegen.sync(target, replace=("record",))

    assert "淘汰的表: record" in target.read_text(encoding="utf-8")


def test_a_new_column_is_appended_to_an_existing_table(tmp_path: Path):
    """同一张表在代码里多出一列：追加到那一列的末尾，已有的列顺序不动。"""
    target = tmp_path / "tables.yaml"
    tablegen.sync(target)
    text = target.read_text(encoding="utf-8")
    grown = text.replace("    - id().value_uuid\n", "    - id().value_uuid\n", 1)
    target.write_text(grown, encoding="utf-8")

    # 代码侧多出一列：把 `kind` 从声明文件里删掉，引擎下一轮应当把它补回来
    trimmed = grown.replace(
        "    - { name: kind, from: store, type: text, doc: 类型标号；由记录自报，顺扫可还原 }\n",
        "",
        1,
    )
    target.write_text(trimmed, encoding="utf-8")

    changed = tablegen.sync(target)

    assert any("新增列" in item for item in changed)
    parsed = {table.name: table for table in load_tables(target)}
    assert parsed["block"].column("kind") is not None


def test_replacing_a_legacy_table_is_explicit(tmp_path: Path):
    """`replace` 点名的旧表从文件里去掉：换形状这件事由调用方明说，不靠猜。"""
    target = tmp_path / "tables.yaml"
    target.write_text(
        "- name: record\n"
        "  tier: derived\n"
        "  rebuild_from: 载体\n"
        "  columns: [id().value_uuid]\n"
        "  primary_key: [value_uuid]\n",
        encoding="utf-8",
    )

    tablegen.sync(target, replace=("record",))

    names = [table.name for table in load_tables(target)]
    assert "record" not in names
    assert {"block", "body"} <= set(names)


def test_a_legacy_table_that_no_longer_parses_still_gets_replaced(tmp_path: Path):
    """旧形状不合今天的判据照样能淘汰：先摘掉、再逐张走解析口。"""
    target = tmp_path / "tables.yaml"
    target.write_text(
        "- name: record\n"
        "  tier: derived\n"
        "  rebuild_from: 载体\n"
        "  columns:\n"
        "    - id(scope).name\n"
        "    - id().value_uuid\n"
        "  primary_key: [name, value_uuid]\n",
        encoding="utf-8",
    )

    tablegen.sync(target, replace=("record",))

    assert "record" not in [table.name for table in load_tables(target)]


def test_sync_is_idempotent(tmp_path: Path):
    """跑第二遍什么都不用动：文件稳定，报告为空。"""
    target = tmp_path / "tables.yaml"
    tablegen.sync(target)
    text = target.read_text(encoding="utf-8")

    assert tablegen.sync(target) == ()
    assert target.read_text(encoding="utf-8") == text


def test_broken_yaml_is_reported(tmp_path: Path):
    """坏 YAML 当场报错，不静默重写一份把人的文件覆盖掉。"""
    target = tmp_path / "tables.yaml"
    target.write_text("name: [unclosed\n", encoding="utf-8")

    with pytest.raises(TableDeclarationError, match="读不出来"):
        tablegen.sync(target)


# ---- 建库：声明文件喂给库 ----


def test_the_index_is_built_from_the_registered_types(tmp_path: Path):
    """一整套走通：登记表 → 声明 → 库；库里看得见 `block` 与 `body`。"""
    declaration = Declaration(kernel_tables())

    with Index.open(tmp_path / "catalog.db", declaration, create=True) as index:
        assert index.tables() == ("block", "body", "hub", "meta")


def test_a_fresh_type_becomes_a_table_in_the_database(tmp_path: Path):
    """**这一条就是"加了类型，表就自己诞生"**：登记之后开库，库与文件都多出那张表。"""
    target = tmp_path / "tables.yaml"

    @dataclass(slots=True)
    class Reported(Block[str]):
        """刚定义的领域类型。"""

    tablegen.sync(target)
    declaration = Declaration(kernel_tables())

    with Index.open(tmp_path / "catalog.db", declaration, create=True) as index:
        assert "reported" in index.tables()
        assert "- name: reported" in target.read_text(encoding="utf-8")


def test_the_shipped_file_and_the_registry_agree(shipped_tables_path: Path):
    """入库的声明文件与登记表现算的结果对得上（防漂移：两边分叉就是错的）。"""
    shipped = {table.name for table in load_tables(shipped_tables_path)}
    computed = {table.name for table in kernel_tables()}

    assert shipped == computed
