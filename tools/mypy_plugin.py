# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""Cairn 的 mypy 插件：把 ``field: attr[T] = 值`` 的字段可见类型识别为 ``T``。

``attr`` 是本项目的一层**声明标记**（``core/attr/__init__.py``）：右侧写的是真实默认值，
运行时不再包装，故字段取出来就是那个值。mypy 看不到这层意思，会把 ``str`` 赋给
``attr[str]`` 判为类型错误（`assignment`）。本插件在类的语义分析阶段把这类字段的**可见类型**
改写成类型参数 ``T``：于是 ``note.title`` 是 ``str``、赋值也合法——与 dataclasses / attrs
官方插件是同一条路数。

范围与约定：
- **简单形式**：``field: attr[T] = 值`` → 插件把可见类型改写为 ``T``。
- **复杂形式**：``field: attr[T] = attr(...)``（需要 ``coerce`` 等特殊处理）→
  尚未实现；插件**不改写**，可见类型保持 ``attr[T]``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mypy.nodes import AssignmentStmt, CallExpr, NameExpr, RefExpr
from mypy.plugin import ClassDefContext, Plugin
from mypy.types import Instance

if TYPE_CHECKING:
    from collections.abc import Callable

BLOCK_FULLNAME = "core.storage.format.block.Block"
ATTR_FULLNAME = "core.attr.attr"


def _is_descriptor_rhs(expr: object) -> bool:
    """右边是否是显式描述符调用 ``Attr(...)``（复杂形式）。"""
    if not isinstance(expr, CallExpr):
        return False
    callee = expr.callee
    return isinstance(callee, RefExpr) and callee.fullname == ATTR_FULLNAME


def _explicit_names(ctx: ClassDefContext) -> set[str]:
    names: set[str] = set()
    for stmt in ctx.cls.defs.body:
        if not isinstance(stmt, AssignmentStmt) or len(stmt.lvalues) != 1:
            continue
        target = stmt.lvalues[0]
        if isinstance(target, NameExpr) and _is_descriptor_rhs(stmt.rvalue):
            names.add(target.name)
    return names


def _rewrite_attr_fields(ctx: ClassDefContext) -> None:
    """把简单形式的 ``Attr[T]`` 字段可见类型改写为 ``T``；复杂形式跳过。"""
    explicit = _explicit_names(ctx)
    for name, symbol in ctx.cls.info.names.items():
        if name in explicit:
            continue
        current = getattr(symbol.node, "type", None)
        if (
            isinstance(current, Instance)
            and current.type.fullname == ATTR_FULLNAME
            and current.args
        ):
            symbol.node.type = current.args[0]  # type: ignore[union-attr]


class CairnPlugin(Plugin):
    def get_base_class_hook(self, fullname: str) -> Callable[[ClassDefContext], None] | None:
        if fullname != BLOCK_FULLNAME:
            return None
        return _rewrite_attr_fields


def plugin(_version: str) -> type[Plugin]:
    return CairnPlugin
