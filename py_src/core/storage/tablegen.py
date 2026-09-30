# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""表生成：登记表 → 表声明 → 声明文件（代码 → 文件 → 库那条路的中段）。

一条类型登记（`registry.TypeDecl`）算出三样东西：

1. **自己的身份列**：`ids` 里那几个字段，列名就是字段名，类型随 `ID` 的字段走；
2. **指向别处的指针列**：`refs` 里每一项落成两列（`body_value_uuid` / `body_value_hash`），
   带限定词的列名加前缀，免得同一张表里两个 ID 的同名字段撞名；
3. **存储层的那几列**：`kind`（程序给的类型标号）、位置与大小（顺扫载体看见的）、
   两个时刻。它们不是 ID 的字段，故只能由本层补上——记录头里没有这些。

**写文件只动它该动的**：已有表与已有列一律照抄，只追加登记表里新出现的表和列。
人手加的东西因此不会被刷掉；要淘汰的旧表由调用方显式点名（`replace`），不靠猜——
"删掉哪个"是有后果的动作，不能隐式发生。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import yaml

from core.exc import TableDeclarationError

from .registry import BODY_TABLE, Registry, TypeDecl
from .tables import (
    Column,
    ColumnSource,
    ColumnType,
    IndexSpec,
    TableSpec,
    Tier,
    column_of,
    reference_column,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

#: 指针里两列的固定顺序：分配形态在前（它是引用方第一眼要的那个），摘要在后。
POINTER_COLUMNS: tuple[str, ...] = ("value_uuid", "value_hash")

#: 类型标号那一列：只有块表有（内容记录没有类型，程序也不给它）。
#: 它是**记录自报**的（`record.KIND_KEY`），故来路是 `store` —— 顺扫即可还原，
#: 索引里那一列只是它的投影（2026-09-30 定：索引只做索引，每一列都要能从载体算回来）。
KIND_COLUMN = ("kind", "text", False, "类型标号；由记录自报，顺扫可还原")

#: 没有类型标号的那张表（内容表）：它只承载身份（含位置段）。
_NO_KIND = frozenset({BODY_TABLE})

#: **不由类型诞生**的那张内核表：`hub` 的主语是载体目录。
#: 它照旧由声明层写死（这里就是那份声明），不与"类型反查"那条路混在一起。
KERNEL_EXTRA_TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        name="hub",
        columns=(
            column_of(
                "name",
                ColumnSource.STORED,
                type=ColumnType.TEXT,
                not_null=True,
                doc="hub 名（目录名）",
            ),
        ),
        tier=Tier.DERIVED,
        owner="core",
        rebuild_from="vault 下的 hub 目录（设计篇 §6）",
        doc="登记表：主语是载体目录、不是 ID；真源是目录本身",
        primary_key=("name",),
    ),
)
"""**不由类型诞生**的那张内核表：`hub` 的主语是载体目录，不是 ID，故照旧由声明层写死。

**这里曾有一张 `edge`（关系索引）表，已删（2026-09-30）**：它零调用方，且形状是按
"关系是一等 DB 行"那套设计的——而口径已经改成"关系由块表达、库只做索引"。
关系落地时按那时的需要重新定索引形状，不在今天预埋（判据同上：没有调用方的结构即脚手架）。
"""


def type_tables(registry: Registry | None = None) -> tuple[TableSpec, ...]:
    """从登记表现算全部表声明（按表名排序，故投影可复现）。

    Raises:
        TableDeclarationError: 有引用指向没登记的表——那是断链，不能带进库。
    """
    source = _registry(registry)
    dangling = [table for table in source.referenced_tables() if source.table(table) is None]
    if dangling:
        raise TableDeclarationError(f"有引用指向没登记的表: {sorted(dangling)}")
    return tuple(table_spec(decl) for decl in source.declarations())


def table_spec(decl: TypeDecl) -> TableSpec:
    """把一个类型登记算成一张表的声明。

    列的顺序：**身份列 → 指针列 → 类型标号**。身份列就是 `ID` 的全部字段
    （`ID_FIELDS`：两套凭证、签发时刻、名字、位置段三列），顺序即 `ID` 的声明顺序。
    故同一份登记每次算出来的文件逐字相同；位置段不再另立观测列——
    "在哪儿"本来就是 ID 记的，库里的行只是它的镜像。
    """
    columns: list[Column] = [column_of(field, ColumnSource.IDENTITY) for field in decl.ids]
    columns.extend(_reference_columns(decl))
    if decl.table not in _NO_KIND:
        name, kind, not_null, doc = KIND_COLUMN
        columns.append(
            column_of(name, ColumnSource.STORED, type=_type_of(kind), not_null=not_null, doc=doc)
        )
    return TableSpec(
        name=decl.table,
        columns=tuple(columns),
        tier=decl.tier,
        owner=decl.owner,
        rebuild_from=_rebuild_from(decl.tier),
        doc=decl.doc or f"类型 {decl.name} 的索引表",
        primary_key=("value_uuid",),
    )


def _rebuild_from(tier: Tier) -> str:
    """重建来源：可重建那一档必须写明来路，真源那一档必须为空。

    两条都由 `TableSpec` 的构造校验兜住——写反了当场报错，不会带进声明文件。
    """
    return "载体记录头（设计篇 §8.5 档一）" if tier is Tier.DERIVED else ""


def sync(
    path: Path,
    *,
    registry: Registry | None = None,
    replace: Sequence[str] = (),
    prune_columns: Mapping[str, Sequence[str]] | None = None,
) -> tuple[str, ...]:
    """把登记表的形状写进声明文件，返回本次动过的表与列（人读的报告）。

    **只追加、不覆写**：

    - 文件不在 → 整份生成（首次运行，声明文件由此诞生）；
    - 文件在 → 登记表里有、文件里没有的表与列追加进去；已有的表与列一个字都不改；
    - `replace` 点名的表从文件里去掉（形状更换时清掉旧表），理由由调用方给。
      点名的表本来就不在文件里时是空操作，且**那句"淘汰了某某"只在真淘汰过时才写**——
      否则文件里会永远挂着一句早已完成的话。

    `prune_columns` 是**列**那一层的同一个出口（表名 → 要点名去掉的列）：淘汰是破坏性动作，
    故一律显式点名、不靠猜。点名的列会同时从"文件里已有的"和"登记表现算的"两侧去掉——
    只去一侧，它下一轮就会被补回来。

    Args:
        path: 声明文件路径。
        registry: 用哪份登记表现算；不给即进程内那一份。
        replace: 要点名淘汰的表。
        prune_columns: 要点名淘汰的列；不给即一个都不动。

    Raises:
        TableDeclarationError: 文件读不出来、坏 YAML，或淘汰之后形状立不起来
            （如把主键列删了）。
    """
    pruned: Mapping[str, Sequence[str]] = {} if prune_columns is None else prune_columns
    if not path.is_file():
        fresh, _removed = _prune(kernel_declarations(registry), pruned)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(fresh), encoding="utf-8")
        return tuple(f"新建表: {table.name}" for table in fresh)

    found = _present(path, replace)
    kept, removed_here = _prune(_surviving(path, found), pruned)
    fresh, _removed_fresh = _prune(kernel_declarations(registry), pruned)
    merged, changed = _merge(kept, fresh, replace=replace)
    report = (
        *changed,
        *(f"淘汰列: {name}" for name in dict.fromkeys(removed_here)),
    )
    if report:
        path.write_text(render(merged, dropped=found), encoding="utf-8")
    return report


def _prune(
    tables: Sequence[TableSpec], pruned: Mapping[str, Sequence[str]]
) -> tuple[tuple[TableSpec, ...], tuple[str, ...]]:
    """按点名把列从表里去掉，返回（剩下的表，真删掉的那些列）。

    点名的列本来就不在时是空操作；点名的表整张不在时同样空操作。
    """
    if not pruned:
        return tuple(tables), ()
    kept: list[TableSpec] = []
    removed: list[str] = []
    for table in tables:
        wanted = pruned.get(table.name)
        if not wanted:
            kept.append(table)
            continue
        drop = set(wanted)
        removed.extend(
            f"{table.name}.{column.name}" for column in table.columns if column.name in drop
        )
        kept.append(_with_columns(table, tuple(c for c in table.columns if c.name not in drop)))
    return tuple(kept), tuple(removed)


def _present(path: Path, replace: Sequence[str]) -> tuple[str, ...]:
    """`replace` 里**确实出现在文件里**的那些表名（空操作与真淘汰由此分开）。"""
    names = {str(item.get("name")) for item in _read_items(path)}
    return tuple(name for name in replace if name in names)


def _surviving(path: Path, found: Sequence[str]) -> tuple[TableSpec, ...]:
    """读声明文件里**没被淘汰**的那些表。

    淘汰项要能"读得进来"：旧形状的表往往按新判据已经不合规（`record` 的
    `id(scope).name` 就是），若先整份解析再删，等于要求旧形状必须仍然合法——
    而淘汰它的理由恰恰是它已经不合法了。故**先按原始项摘掉，再逐张走严格解析口**。
    """
    dropped = set(found)
    raw = [item for item in _read_items(path) if item.get("name") not in dropped]
    return _parse_items(raw)


def _read_items(path: Path) -> list[dict[str, object]]:
    """把声明文件读成"一项一张表的原始映射"；坏 YAML 与根不是列表即报错。"""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise TableDeclarationError(f"表声明文件读不出来: {path}（{error}）") from error
    if not isinstance(raw, list) or not raw:
        raise TableDeclarationError(f"表声明文件必须是一张表一项的非空列表: {path}")
    items: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise TableDeclarationError(f"每一项表声明必须是映射: {item!r}")
        items.append(item)
    return items


def _parse_items(items: Sequence[dict[str, object]]) -> tuple[TableSpec, ...]:
    """把原始项逐张走严格解析口（与 :func:`tables.load_tables` 同一套判据）。

    一件都不剩不算错：那是"文件里只有被淘汰的旧表"这一种情形，
    随后由现算的声明把文件补满。
    """
    return tuple(TableSpec.from_mapping(item) for item in items)


def render(tables: Sequence[TableSpec], *, dropped: Sequence[str] = ()) -> str:
    """把表声明渲染成声明文件的正文（表在文件里是给人读的，故缩进展开）。

    **空行是排版的一部分**：文件头与第一张表之间、每两张表之间都空一行。
    这份文件要给人看、给人改，表与表贴成一摞读起来费力；空行不进解析口
    （YAML 的块序列本来就用空行分隔），故它只影响观感，不影响任何判据。

    Args:
        tables: 要渲染的表，顺序即书写顺序。
        dropped: **本次真的淘汰掉**的旧表名；只在确实淘汰过时才写那句提示，
            否则文件里会永远挂着一句"淘汰了某某"的旧话。
    """
    sections = ["\n".join(_header_lines(dropped))]
    sections.extend(_render_table(table) for table in tables)
    return "\n\n".join(sections) + "\n"


def _render_table(table: TableSpec) -> str:
    """渲染一张表：列一项一行，绑定列写字面式，非绑定列写映射。"""
    lines = [f"- name: {table.name}"]
    lines.extend(f"  {key}: {_scalar(value)}" for key, value in _table_head(table))
    lines.append("  columns:")
    lines.extend(_render_column(column) for column in table.columns)
    lines.append(f"  primary_key: {_flow(list(table.primary_key))}")
    if table.indexes:
        lines.append("  indexes:")
        lines.extend(_render_index(index) for index in table.indexes)
    return "\n".join(lines)


def _table_head(table: TableSpec) -> tuple[tuple[str, object], ...]:
    """表级字段的书写顺序：说明、档、归属、来源。"""
    head: list[tuple[str, object]] = []
    if table.doc:
        head.append(("doc", table.doc))
    head.append(("tier", table.tier.value))
    head.append(("owner", table.owner))
    if table.rebuild_from:
        head.append(("rebuild_from", table.rebuild_from))
    return tuple(head)


def _render_column(column: Column) -> str:
    """渲染一列：绑定列写字面式 `id(名字).字段`，其余写映射。"""
    if column.source is ColumnSource.IDENTITY:
        return f"    - id().{column.name}"
    if column.source is ColumnSource.REFERENCE:
        return f"    - id({column.qualifier}).{column.name}"
    fields = [
        f"name: {column.name}",
        f"from: {column.source.value}",
        f"type: {column.type.value}",
    ]
    fields.extend(f"{key}: {value}" for key, value in _column_flags(column))
    if column.doc:
        fields.append(f"doc: {column.doc}")
    return "    - { " + ", ".join(fields) + " }"


def _column_flags(column: Column) -> tuple[tuple[str, object], ...]:
    """列上的约束开关：只写开了的，保持文件短。"""
    flags: list[tuple[str, object]] = []
    if column.unique:
        flags.append(("unique", True))
    if column.not_null:
        flags.append(("not_null", True))
    if column.default is not None:
        flags.append(("default", column.default))
    return tuple(flags)


def _render_index(index: IndexSpec) -> str:
    """渲染一个索引声明。"""
    fields = [f"columns: {_flow(list(index.columns))}"]
    if index.unique:
        fields.append("unique: true")
    if index.doc:
        fields.append(f"doc: {index.doc}")
    return "    - { " + ", ".join(fields) + " }"


def _scalar(value: object) -> str:
    """渲染一个标量字段；字符串一律按 JSON 的规矩加引号（中文说明里什么都可能有）。"""
    if not isinstance(value, str):
        return str(value)
    if value and not value.startswith(("-", "?", ":")) and _PLAIN.match(value):
        return value
    return json.dumps(value, ensure_ascii=False)


#: 能不加引号直接写的字符串（YAML 的裸标量）：字母数字加少量符号。
_PLAIN = re.compile(r"^[A-Za-z0-9_./]+$")


def _flow(items: Sequence[str]) -> str:
    """渲染一个行内序列。"""
    return "[" + ", ".join(items) + "]"


def _header_lines(dropped: Sequence[str]) -> list[str]:
    """声明文件的文件头（一个整体，与第一张表之间由 :func:`render` 空一行隔开）。"""
    lines = [
        "# SPDX-FileCopyrightText: 2026 HanYang06",
        "# SPDX-License-Identifier: Apache-2.0",
        "#",
        "# 索引库的表声明。**这份文件由代码写出来**：谁用了 ID，谁的名字就在这里（设计篇 §8）。",
        "# 引擎在开库时读它、把它编译成建表语句；人也能改它——加了什么，引擎下次只补不删。",
        "#",
        "# 列的来路三种写法：",
        "#   id().字段       本行主语的 ID 字段（列名就是字段名，类型随 ID 走）",
        "#   id(名字).字段   指向别处的指针（只带两套凭证，列名加名字前缀）",
        "#   { name, from, type, doc }  存储层观测（store）/ 程序给出（prog）/ 派生（digest）",
    ]
    if dropped:
        lines.extend(("#", f"# 本次更换形状淘汰的表: {', '.join(dropped)}"))
    return lines


def _merge(
    existing: tuple[TableSpec, ...],
    fresh: tuple[TableSpec, ...],
    *,
    replace: Sequence[str],
) -> tuple[tuple[TableSpec, ...], tuple[str, ...]]:
    """合并：文件赢、登记表只补缺；`replace` 点名的表从文件里去掉。

    `replace` 是**声明式的意图**：点到的表若本来就不在文件里，那是空操作（幂等）；
    真正要它做的事是"下次读到它时不要"。故这里不因为名字不在就报错。
    """
    dropped = set(replace)
    kept = [table for table in existing if table.name not in dropped]
    by_name = {table.name: table for table in kept}
    changed: list[str] = []
    for table in fresh:
        current = by_name.get(table.name)
        if current is None:
            kept.append(table)
            changed.append(f"新增表: {table.name}")
            continue
        grown, columns_added = _grow(current, table)
        if columns_added:
            kept[kept.index(current)] = grown
            changed.extend(f"新增列: {table.name}.{name}" for name in columns_added)
    return tuple(kept), tuple(changed)


def _grow(current: TableSpec, fresh: TableSpec) -> tuple[TableSpec, tuple[str, ...]]:
    """给一张已有的表补上登记表里新出现的列；已有的列顺序与内容都不动。"""
    have = {column.sql_name for column in current.columns}
    missing = [column for column in fresh.columns if column.sql_name not in have]
    if not missing:
        return current, ()
    return _with_columns(current, (*current.columns, *missing)), tuple(
        column.sql_name for column in missing
    )


def _with_columns(table: TableSpec, columns: Sequence[Column]) -> TableSpec:
    """换一版列清单，其余字段照抄（列增长是唯一会动到已存在表的地方）。"""
    return TableSpec(
        name=table.name,
        columns=tuple(columns),
        tier=table.tier,
        indexes=table.indexes,
        owner=table.owner,
        rebuild_from=table.rebuild_from,
        doc=table.doc,
        primary_key=table.primary_key,
    )


def _reference_columns(decl: TypeDecl) -> tuple[Column, ...]:
    """把一个类型的引用算成指针列：每一项落成两列（分配形态与摘要形态）。"""
    return tuple(
        reference_column(table, name) for table in decl.refs.values() for name in POINTER_COLUMNS
    )


def _type_of(name: str) -> ColumnType:
    """中立类型名 → `ColumnType`；名字写错即报错（常量表写坏了要当场看得见）。"""
    try:
        return ColumnType(name)
    except ValueError as error:
        raise TableDeclarationError(f"未知列类型 {name!r}") from error


def kernel_declarations(registry: Registry | None = None) -> tuple[TableSpec, ...]:
    """内核的**全部**表声明：类型派生的（`block` / `body`）＋ 不由类型诞生的（`hub`）。

    顺序确定（类型表按表名、补的那张按声明顺序），故文件与库每次算出来都一样。
    """
    return (*type_tables(registry), *KERNEL_EXTRA_TABLES)


def _registry(registry: Registry | None) -> Registry:
    """取登记表；不给即用进程内那一份。"""
    from .registry import REGISTRY  # noqa: PLC0415

    return REGISTRY if registry is None else registry


__all__ = [
    "KERNEL_EXTRA_TABLES",
    "KIND_COLUMN",
    "POINTER_COLUMNS",
    "kernel_declarations",
    "render",
    "sync",
    "table_spec",
    "type_tables",
]
