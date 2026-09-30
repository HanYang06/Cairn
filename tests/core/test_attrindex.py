# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""速查契约：按属性值找块，而它始终只是块的一份派生。

要真建库——速查从块整份重算，验的是"块怎么写、它就怎么查得到"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from core.attr import attr  # noqa: TC001 — 注解由 get_type_hints 在运行期解析，必须真导入
from core.exc import TableDeclarationError
from core.init import Kernel
from core.storage.format.block import Block, Body, register_type
from core.storage.registry import REGISTRY

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


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


# ---- 查得到 ----


def test_finds_a_block_by_its_attribute(tmp_path: Path):
    """存的时候给了属性，重算出来的表就按它查得到。"""

    @dataclass(slots=True)
    class NoteData(Block[None]):
        """标题可查的测试类型。"""

        __table__ = "notedata"
        __indexed__ = ("title",)

        title: attr[str] = ""

    with Kernel.create(tmp_path / "vault") as kernel:
        first = kernel.store(b"b1", kind="notedata", attrs={"title": "第一篇"})
        second = kernel.store(b"b2", kind="notedata", attrs={"title": "第二篇"})

        table = kernel.reindex()

        assert table.find("notedata", "title", "第一篇") == (first.value_uuid,)
        assert table.find("notedata", "title", "第二篇") == (second.value_uuid,)
        assert table.find("notedata", "title", "没有这一篇") == ()


def test_same_value_in_two_blocks_shares_one_entry(tmp_path: Path):
    """同一属性值落在两个块上：倒排那一项把两个身份都收着。"""

    @dataclass(slots=True)
    class NoteData(Block[None]):
        """标题可查的测试类型。"""

        __table__ = "notedata"
        __indexed__ = ("title",)

        title: attr[str] = ""

    with Kernel.create(tmp_path / "vault") as kernel:
        first = kernel.store(b"b1", kind="notedata", attrs={"title": "同名"})
        second = kernel.store(b"b2", kind="notedata", attrs={"title": "同名"})

        found = kernel.reindex().find("notedata", "title", "同名")

        assert sorted(found) == sorted([first.value_uuid, second.value_uuid])


def test_find_any_crosses_types(tmp_path: Path):
    """跨类型按同一个属性名查：`find_any` 把各类型的命中并起来。"""

    @dataclass(slots=True)
    class NoteData(Block[None]):
        """标题可查的测试类型。"""

        __table__ = "notedata"
        __indexed__ = ("title",)

        title: attr[str] = ""

    @dataclass(slots=True)
    class ProjectData(Block[None]):
        """标题也可查的另一个类型。"""

        __table__ = "projectdata"
        __indexed__ = ("title",)

        title: attr[str] = ""

    with Kernel.create(tmp_path / "vault") as kernel:
        note = kernel.store(b"n", kind="notedata", attrs={"title": "计划"})
        project = kernel.store(b"p", kind="projectdata", attrs={"title": "计划"})

        found = kernel.reindex().find_any("title", "计划")

        assert sorted(found) == sorted([note.value_uuid, project.value_uuid])


def test_attributes_lists_what_is_queryable(tmp_path: Path):
    """表能说出"可以按什么查"——界面拿它显示可选条件。"""

    @dataclass(slots=True)
    class NoteData(Block[None]):
        """标题可查、标签不查的测试类型。"""

        __table__ = "notedata"
        __indexed__ = ("title",)

        title: attr[str] = ""
        tags: attr[dict[str, int]] = field(default_factory=dict)

    with Kernel.create(tmp_path / "vault") as kernel:
        kernel.store(b"b1", kind="notedata", attrs={"title": "t", "tags": {"a": 1}})

        assert kernel.reindex().attributes == (("notedata", "title"),)


# ---- 只是派生：查不到的三种情形 ----


def test_undeclared_attributes_are_not_indexed(tmp_path: Path):
    """没有声明要查的属性不进表：领域只为自己要用的那几条付代价。"""

    @dataclass(slots=True)
    class NoteData(Block[None]):
        """只声明标题可查的测试类型。"""

        __table__ = "notedata"
        __indexed__ = ("title",)

        title: attr[str] = ""
        author: attr[str] = ""

    with Kernel.create(tmp_path / "vault") as kernel:
        kernel.store(b"b1", kind="notedata", attrs={"title": "t", "author": "甲"})

        assert kernel.reindex().find("notedata", "author", "甲") == ()


def test_deleted_blocks_are_not_in_the_index(tmp_path: Path):
    """删掉的块不在表里：记录还在盘上，但它已经不活着了（判据以索引行为准）。"""

    @dataclass(slots=True)
    class NoteData(Block[None]):
        """标题可查的测试类型。"""

        __table__ = "notedata"
        __indexed__ = ("title",)

        title: attr[str] = ""

    with Kernel.create(tmp_path / "vault") as kernel:
        keep = kernel.store(b"b1", kind="notedata", attrs={"title": "留下"})
        gone = kernel.store(b"b2", kind="notedata", attrs={"title": "删掉"})
        kernel.drop(gone.value_uuid)

        table = kernel.reindex()

        assert table.find("notedata", "title", "删掉") == ()
        assert table.find("notedata", "title", "留下") == (keep.value_uuid,)


def test_a_block_without_that_attribute_is_skipped(tmp_path: Path):
    """块没给那个属性：它不进表，也不报错。"""

    @dataclass(slots=True)
    class NoteData(Block[None]):
        """标题可查的测试类型。"""

        __table__ = "notedata"
        __indexed__ = ("title",)

        title: attr[str] = ""

    with Kernel.create(tmp_path / "vault") as kernel:
        kernel.store(b"b1", kind="notedata")

        assert kernel.reindex().find("notedata", "title", "") == ()


def test_int_and_bool_do_not_collide(tmp_path: Path):
    """`1` 与 `True` 在 Python 里相等，查表不能把它们当成同一个值。"""

    @dataclass(slots=True)
    class Counter(Block[None]):
        """数值可查的测试类型。"""

        __table__ = "counter"
        __indexed__ = ("count",)

        count: attr[int] = 0

    with Kernel.create(tmp_path / "vault") as kernel:
        one = kernel.store(b"b1", kind="counter", attrs={"count": 1})

        found = kernel.reindex().find("counter", "count", True)

        assert found == (), "布尔与整数是两回事"
        assert kernel.reindex().find("counter", "count", 1) == (one.value_uuid,)


# ---- 声明写坏了当场报 ----


def test_indexing_an_unknown_attribute_is_refused():
    """声明要查的属性不存在：登记期报错，不静默留个永远空着的条件。"""
    with pytest.raises(TableDeclarationError, match="不是它的属性"):

        @dataclass(slots=True)
        class Broken(Block[None]):
            """声明了一个不存在的属性的测试类型。"""

            __table__ = "broken"
            __indexed__ = ("没有这个",)

            title: attr[str] = ""


def test_indexing_a_container_is_refused():
    """容器属性不可查：值不可哈希，按它查只能是"包含"式。"""
    with pytest.raises(TableDeclarationError, match="容器"):

        @dataclass(slots=True)
        class Bulky(Block[None]):
            """把容器声明成可查的测试类型。"""

            __table__ = "bulky"
            __indexed__ = ("tags",)

            tags: attr[dict[str, int]] = field(default_factory=dict)
