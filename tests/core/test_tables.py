# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""表声明契约：解析口严格、DDL 由声明编译、签名与书写顺序及注释无关。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.exc import TableDeclarationError
from core.storage.tables import (
    Column,
    ColumnType,
    Declaration,
    IndexSpec,
    TableSpec,
    Tier,
    kernel_tables,
    load_tables,
)

if TYPE_CHECKING:
    from pathlib import Path


def _mapping(**overrides: object) -> dict[str, object]:
    """一份最小的合法表声明，可按需改写某一项。"""
    base: dict[str, object] = {
        "name": "t",
        "tier": "derived",
        "rebuild_from": "载体记录头",
        "columns": [
            {"name": "id", "from": "prog", "type": "text"},
            {"name": "payload", "from": "prog", "type": "blob"},
        ],
        "primary_key": ["id"],
    }
    base.update(overrides)
    return base


# ---- 解析口 ----


def test_reads_a_full_declaration():
    """完整声明逐项读回。"""
    spec = TableSpec.from_mapping(
        _mapping(
            owner="note",
            doc="说明",
            indexes=[{"columns": ["payload"], "unique": True}],
        )
    )

    assert spec.name == "t"
    assert spec.tier is Tier.DERIVED
    assert spec.rebuild_from == "载体记录头"
    assert spec.owner == "note"
    assert spec.column_names() == ("id", "payload")
    assert spec.primary_key == ("id",)
    assert spec.indexes == (IndexSpec(columns=("payload",), unique=True),)


def test_owner_defaults_to_core():
    """归属不写即内核表。"""
    assert TableSpec.from_mapping(_mapping()).owner == "core"


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"unknown": 1}, "未知项"),
        ({"name": ""}, "标识符"),
        ({"name": "1abc"}, "标识符"),
        ({"name": "有中文"}, "标识符"),
        ({"name": 7}, "标识符"),
        ({"tier": "middle"}, "未知重建档"),
        ({"tier": 1}, "重建档"),
        ({"rebuild_from": ""}, "重建来源"),
        ({"rebuild_from": 3}, "必须是字符串"),
        ({"columns": ()}, "非空的列清单"),
        ({"indexes": {"columns": ["payload"]}}, "序列"),
    ],
)
def test_parse_gate_rejects_bad_declarations(overrides: dict[str, object], match: str):
    """未知项、非法名字与类型、缺必填项一律报错，不静默忽略。"""
    with pytest.raises(TableDeclarationError, match=match):
        TableSpec.from_mapping(_mapping(**overrides))


def test_source_tier_forbids_rebuild_source():
    """真源表不允许写重建来源：可重建与真源不可兼得，必须明说。"""
    with pytest.raises(TableDeclarationError, match="不可兼得"):
        TableSpec.from_mapping(_mapping(tier="source", rebuild_from="载体"))

    spec = TableSpec.from_mapping(_mapping(tier="source", rebuild_from=""))
    assert spec.tier is Tier.SOURCE


def test_columns_are_checked_for_duplicates_and_one_key():
    """列名不许重复，主键恰需一列。"""
    with pytest.raises(TableDeclarationError, match="列名重复"):
        TableSpec.from_mapping(
            _mapping(
                columns=[
                    {"name": "id", "from": "prog", "type": "text"},
                    {"name": "id", "from": "prog", "type": "text"},
                ]
            )
        )
    with pytest.raises(TableDeclarationError, match="多个身份列"):
        TableSpec.from_mapping(
            _mapping(
                columns=["id().value_uuid", "id().value_hash"],
                primary_key=[],
            )
        )
    with pytest.raises(TableDeclarationError, match="必须有主键"):
        TableSpec.from_mapping(
            _mapping(
                columns=[
                    {"name": "a", "from": "prog", "type": "text"},
                    {"name": "b", "from": "prog", "type": "text"},
                ],
                primary_key=[],
            )
        )
    with pytest.raises(TableDeclarationError, match="主键列不存在"):
        TableSpec.from_mapping(
            _mapping(
                columns=[{"name": "id", "from": "prog", "type": "text"}],
                primary_key=["nope"],
            )
        )


def test_unknown_column_and_index_keys_are_rejected():
    """列与索引的未知项同样报错（写错了要看得见）。"""
    with pytest.raises(TableDeclarationError, match="未知项"):
        TableSpec.from_mapping(
            _mapping(columns=[{"name": "id", "from": "prog", "type": "text", "typo": 1}])
        )
    with pytest.raises(TableDeclarationError, match="未知项"):
        TableSpec.from_mapping(_mapping(indexes=[{"column": ["id"]}]))


def test_flags_must_be_booleans():
    """约束开关只收布尔：写成字符串会静默当真，故拒绝。"""
    with pytest.raises(TableDeclarationError, match="布尔"):
        TableSpec.from_mapping(
            _mapping(columns=[{"name": "id", "from": "prog", "type": "text", "not_null": "yes"}])
        )
    with pytest.raises(TableDeclarationError, match="布尔"):
        TableSpec.from_mapping(_mapping(indexes=[{"columns": ["payload"], "unique": "yes"}]))


def test_index_columns_must_exist():
    """索引列必须在表内。"""
    with pytest.raises(TableDeclarationError, match="不在表内"):
        TableSpec.from_mapping(_mapping(indexes=[{"columns": ["missing"]}]))


def test_duplicate_index_is_rejected_regardless_of_column_order():
    """同一列组合（无论书写顺序）不许声明两次。"""
    with pytest.raises(TableDeclarationError, match="索引重复"):
        TableSpec.from_mapping(
            _mapping(
                indexes=[
                    {"columns": ["payload", "id"]},
                    {"columns": ["id", "payload"]},
                ]
            )
        )


# ---- DDL 编译 ----


def test_default_literals_follow_column_type():
    """默认值按列类型编成字面量；类型不符即报错。"""
    text = Column("t", ColumnType.TEXT, default="it's")
    assert text.ddl() == "\"t\" TEXT DEFAULT 'it''s'"
    assert Column("n", ColumnType.INTEGER, default=7).ddl() == '"n" INTEGER DEFAULT 7'
    assert Column("r", ColumnType.REAL, default=0.5).ddl() == '"r" REAL DEFAULT 0.5'
    assert Column("b", ColumnType.BLOB, default=b"\x00\xff").ddl() == "\"b\" BLOB DEFAULT X'00ff'"
    assert Column("f", ColumnType.BOOLEAN, default=True).ddl() == '"f" INTEGER DEFAULT 1'

    with pytest.raises(TableDeclarationError, match="不符"):
        Column("bad", ColumnType.INTEGER, default="7").ddl()
    with pytest.raises(TableDeclarationError, match="不符"):
        Column("bad", ColumnType.TEXT, default=7).ddl()


def test_create_table_ddl_quotes_identifiers_and_orders_constraints():
    """建表语句：标识符加引号（防保留字），约束按固定顺序。"""
    spec = TableSpec.from_mapping(
        _mapping(
            columns=[
                {"name": "id", "from": "prog", "type": "text", "not_null": True},
                {
                    "name": "state",
                    "from": "prog",
                    "type": "text",
                    "not_null": True,
                    "default": "new",
                },
            ]
        )
    )

    assert spec.create_table_ddl() == (
        'CREATE TABLE IF NOT EXISTS "t" ('
        '"id" TEXT NOT NULL, '
        "\"state\" TEXT NOT NULL DEFAULT 'new', "
        'PRIMARY KEY ("id"))'
    )


def test_index_names_are_derived_from_table_and_sorted_columns():
    """索引名由表名与列组合推出（列按名排序），故书写顺序不影响它；唯一索引带 UNIQUE。"""
    spec = TableSpec.from_mapping(
        _mapping(
            indexes=[
                {"columns": ["payload", "id"]},
                {"columns": ["id"], "unique": True},
            ]
        )
    )

    assert spec.index_names() == ("idx_t_id", "idx_t_id_payload")
    statements = spec.create_index_ddl()
    assert statements[0] == 'CREATE UNIQUE INDEX IF NOT EXISTS "idx_t_id" ON "t" ("id")'
    # 索引名里的列按名排序，但 DDL 里保持声明顺序——索引的列顺序是有语义的
    assert statements[1] == (
        'CREATE INDEX IF NOT EXISTS "idx_t_id_payload" ON "t" ("payload", "id")'
    )


def test_ddl_creates_table_before_indexes():
    """建表语句先于建索引语句。"""
    spec = TableSpec.from_mapping(_mapping(indexes=[{"columns": ["payload"]}]))

    statements = spec.ddl()

    assert statements[0].startswith("CREATE TABLE IF NOT EXISTS")
    assert statements[1].startswith("CREATE INDEX IF NOT EXISTS")


def test_add_column_ddl_and_its_limits():
    """补列：普通列可补，主键 / 唯一 / 非空无默认值的列补不上。"""
    spec = TableSpec.from_mapping(
        _mapping(
            columns=[
                {"name": "id", "from": "prog", "type": "text"},
                {"name": "payload", "from": "prog", "type": "blob"},
                {"name": "u", "from": "prog", "type": "text", "unique": True},
            ]
        )
    )

    assert spec.add_column_ddl("payload") == 'ALTER TABLE "t" ADD COLUMN "payload" BLOB'
    with pytest.raises(TableDeclarationError, match="没有列"):
        spec.add_column_ddl("nope")
    with pytest.raises(TableDeclarationError, match="补不上"):
        spec.add_column_ddl("u")
    for column in (
        Column("k", ColumnType.TEXT, primary_key=True),
        Column("u", ColumnType.TEXT, unique=True),
        Column("n", ColumnType.TEXT, not_null=True),
    ):
        assert not column.can_be_added()


def test_signature_ignores_doc_and_writing_order():
    """签名是开库比对依据：注释与书写顺序都不该让库打不开。"""
    left = TableSpec.from_mapping(
        _mapping(
            doc="甲的说明",
            indexes=[{"columns": ["payload"]}],
        )
    )
    right = TableSpec.from_mapping(
        {
            "name": "t",
            "tier": "derived",
            "rebuild_from": "载体记录头",
            "doc": "乙的说明",
            "indexes": [{"columns": ["payload"]}],
            "columns": [
                {"name": "payload", "from": "prog", "type": "blob", "doc": "载荷"},
                {"name": "id", "from": "prog", "type": "text"},
            ],
            "primary_key": ["id"],
        }
    )

    assert left.signature() == right.signature()


# ---- 声明集 ----


def test_declaration_rejects_duplicate_tables_and_empty_set():
    """同名表重复、空声明集都报错。"""
    table = TableSpec.from_mapping(_mapping())
    with pytest.raises(TableDeclarationError, match="重复"):
        Declaration((table, table))
    with pytest.raises(TableDeclarationError, match="为空"):
        Declaration(())


def test_declaration_rejects_cross_table_index_collision():
    """跨表撞索引名要在声明集这一层拦下：SQLite 的索引名整库唯一，撞名会被静默跳过。"""
    left = TableSpec.from_mapping(
        {
            "name": "a",
            "tier": "derived",
            "rebuild_from": "载体",
            "columns": [
                {"name": "id", "from": "prog", "type": "text"},
                {"name": "b", "from": "prog", "type": "text"},
                {"name": "c", "from": "prog", "type": "text"},
            ],
            "indexes": [{"columns": ["b", "c"]}],
            "primary_key": ["id"],
        }
    )
    right = TableSpec.from_mapping(
        {
            "name": "a_b",
            "tier": "derived",
            "rebuild_from": "载体",
            "columns": [
                {"name": "id", "from": "prog", "type": "text"},
                {"name": "c", "from": "prog", "type": "text"},
            ],
            "indexes": [{"columns": ["c"]}],
            "primary_key": ["id"],
        }
    )

    with pytest.raises(TableDeclarationError, match="撞名"):
        Declaration((left, right))


def test_declaration_cannot_take_the_index_reserved_name():
    """`meta` 是索引库自用表名，声明里不得占用（否则开库时两套东西打架）。"""
    with pytest.raises(TableDeclarationError, match="自用表名"):
        Declaration((TableSpec.from_mapping(_mapping(name="meta")),))


def test_declaration_ddl_and_signature_are_ordered_by_table_name():
    """声明集的 DDL 与签名都按表名排序，使执行与比对都确定。"""
    zeta = TableSpec.from_mapping(_mapping(name="zeta"))
    alpha = TableSpec.from_mapping(_mapping(name="alpha"))
    declaration = Declaration((zeta, alpha))

    assert declaration.table("zeta") is zeta
    assert declaration.table("nope") is None
    assert declaration.ddl()[0].startswith('CREATE TABLE IF NOT EXISTS "alpha"')
    assert declaration.signature().splitlines()[0].startswith("table=alpha")


# ---- 内核那几张表 ----


def test_kernel_tables_declare_and_compile():
    """内核表由类型登记现算：`block` / `body` 派生，`hub` / `edge` 另写。"""
    declaration = Declaration(kernel_tables())

    assert {table.name for table in declaration.tables} == {"block", "body", "hub", "edge"}
    assert all(statement.startswith("CREATE ") for statement in declaration.ddl())

    block = declaration.table("block")
    assert block is not None
    assert block.column_names() == (
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
    assert block.primary_key == ("value_uuid",)
    assert block.column("slot_head") is None
    assert block.index_name(IndexSpec(columns=("value_hash",))) == "idx_block_value_hash"

    body = declaration.table("body")
    assert body is not None
    assert body.column_names() == (
        "name",
        "value_uuid",
        "value_hash",
        "birth_time",
        "in_hub",
        "in_hub_pack",
        "in_pack_slot",
    )
    assert body.column("kind") is None, "内容记录没有类型标号"


def test_kernel_tables_are_either_rebuildable_or_explicitly_source():
    """每张内核表的档都要与事实相符：可重建的写明来源，是真源的**不许**写来源。

    `edge` 目前是真源（关系数据只活在库里，等关系块落地才改回可重建），
    故它是"两档都合法、但必须各写各的"这一条的现成例子。
    """
    for table in kernel_tables():
        if table.tier is Tier.DERIVED:
            assert table.rebuild_from, table.name
        else:
            assert table.tier is Tier.SOURCE
            assert not table.rebuild_from, table.name

    sourced = {table.name for table in kernel_tables() if table.tier is Tier.SOURCE}
    assert sourced == {"edge"}


# ---- 表声明文件的读取 ----


def test_shipped_tables_file_loads(shipped_tables_path: Path):
    """入库的 `config/tables.yaml` 可读，且逐张过解析口。"""
    tables = load_tables(shipped_tables_path)

    assert {table.name for table in tables} == {"block", "body", "hub", "edge"}
    assert shipped_tables_path.name == "tables.yaml"


def test_loader_reports_a_missing_file(tmp_path: Path):
    """文件不在即报错，不静默出一份空声明（空声明会把库里的表判成多出来的）。"""
    with pytest.raises(TableDeclarationError, match="不在"):
        load_tables(tmp_path / "nope.yaml")


def test_kernel_tables_come_from_the_registry_not_from_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`kernel_tables()` 问的是**登记表**，不是文件：文件不在也照样算得出来。

    这是"表会自己诞生"在代码上的落点——文件是投影，投影丢了大不了重生成一遍。
    """
    monkeypatch.setattr("core.storage.tables.tables_path", lambda: tmp_path / "nope.yaml")

    assert [table.name for table in kernel_tables()] == ["block", "body", "hub", "edge"]


def test_loader_reports_broken_yaml(tmp_path: Path):
    """读不成 YAML / 根不是列表 / 项不是映射：三种都当场报错。"""
    broken = tmp_path / "broken.yaml"
    broken.write_text("name: [unclosed\n", encoding="utf-8")
    with pytest.raises(TableDeclarationError, match="读不出来"):
        load_tables(broken)

    empty = tmp_path / "empty.yaml"
    empty.write_text("- 1\n", encoding="utf-8")
    with pytest.raises(TableDeclarationError, match="必须是映射"):
        load_tables(empty)


def test_loader_propagates_parse_gate_errors(tmp_path: Path):
    """文件写得不对（比如少写 from 的列）：解析口的报错原样出来。"""
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "- name: t\n"
        "  tier: derived\n"
        "  rebuild_from: 载体\n"
        "  columns:\n"
        "    - { name: kind, type: text }\n"
        "  primary_key: [kind]\n",
        encoding="utf-8",
    )

    with pytest.raises(TableDeclarationError, match="from"):
        load_tables(bad)


# ---- 剩余的解析口分支 ----


def test_unique_column_compiles():
    """列级唯一由 SQLite 的列约束表达。"""
    assert Column("u", ColumnType.TEXT, unique=True).ddl() == '"u" TEXT UNIQUE'


def test_primary_key_may_sit_anywhere_in_the_list():
    """主键列不一定要写在最前：取主键要能扫到后面那列。"""
    spec = TableSpec.from_mapping(
        _mapping(
            columns=[
                {"name": "payload", "from": "prog", "type": "blob"},
                {"name": "id", "from": "prog", "type": "text"},
            ]
        )
    )

    assert spec.primary_key == ("id",)
    assert spec.column("payload") is not None
    assert spec.column("nope") is None


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"owner": 7}, "归属"),
        ({"doc": 7}, "说明"),
        ({"columns": ["id().value_uuid"], "primary_key": ["nope"]}, "主键列不存在"),
        ({"columns": [{"name": "id", "from": "prog", "type": 7}]}, "必须是字符串"),
        (
            {
                "columns": [
                    {"name": "id", "from": "prog", "type": "text"},
                    {"name": "x", "from": "prog", "type": "json"},
                ],
                "primary_key": ["id"],
            },
            "未知列类型",
        ),
        ({"indexes": ["id"]}, "必须是映射"),
        ({"indexes": [{"columns": "payload"}]}, "非空的列组合"),
        ({"indexes": [{"columns": [7]}]}, "必须是字符串"),
    ],
)
def test_parse_gate_covers_remaining_branches(overrides: dict[str, object], match: str):
    """解析口剩下的分支同样报错：类型词表、非映射项、空列组合、非标识符列名。"""
    with pytest.raises(TableDeclarationError, match=match):
        TableSpec.from_mapping(_mapping(**overrides))
