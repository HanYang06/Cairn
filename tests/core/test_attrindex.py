# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""速查契约：按属性值找块，而它始终只是块的一份派生。

要真建库——速查从块整份重算，验的是"块怎么写、它就怎么查得到"。
可查与否由**属性自己的声明**给出（`attr(..., indexed=True)`），不再另立一份名单。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.attr import attr
from core.conf.types import TypeSpec
from core.exc import TableDeclarationError
from core.init import Kernel
from core.storage.format.block import Block, declare_type, install_core_types
from core.storage.format.id import ID
from core.storage.registry import REGISTRY, TypeDecl

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def clean_registry() -> Iterator[None]:
    """每个用例一份干净的登记，**用完还原**（与 `test_attr.py` 同一套）。"""
    REGISTRY.clear()
    install_core_types()
    yield
    REGISTRY.clear()
    install_core_types()


# ---- 查得到 ----


def test_finds_a_block_by_its_attribute(tmp_path: Path):
    """存的时候给了属性，重算出来的表就按它查得到。"""

    class NoteData(Block):
        """标题可查的测试类型。"""

        __table__ = "notedata"

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.title = attr(default="", indexed=True)

    with Kernel.create(tmp_path / "vault") as kernel:
        first = kernel.store(b"b1", kind="notedata", attrs={"title": "第一篇"})
        second = kernel.store(b"b2", kind="notedata", attrs={"title": "第二篇"})

        table = kernel.reindex()

        assert table.find("notedata", "title", "第一篇") == (first.value_uuid,)
        assert table.find("notedata", "title", "第二篇") == (second.value_uuid,)
        assert table.find("notedata", "title", "没有这一篇") == ()


def test_same_value_in_two_blocks_shares_one_entry(tmp_path: Path):
    """同一属性值落在两个块上：倒排那一项把两个身份都收着。"""

    class NoteData(Block):
        """标题可查的测试类型。"""

        __table__ = "notedata"

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.title = attr(default="", indexed=True)

    with Kernel.create(tmp_path / "vault") as kernel:
        first = kernel.store(b"b1", kind="notedata", attrs={"title": "同名"})
        second = kernel.store(b"b2", kind="notedata", attrs={"title": "同名"})

        found = kernel.reindex().find("notedata", "title", "同名")

        assert sorted(found) == sorted([first.value_uuid, second.value_uuid])


def test_find_any_crosses_types(tmp_path: Path):
    """跨类型按同一个属性名查：`find_any` 把各类型的命中并起来。"""

    class NoteData(Block):
        """标题可查的测试类型。"""

        __table__ = "notedata"

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.title = attr(default="", indexed=True)

    class ProjectData(Block):
        """标题也可查的另一个类型。"""

        __table__ = "projectdata"

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.title = attr(default="", indexed=True)

    with Kernel.create(tmp_path / "vault") as kernel:
        note = kernel.store(b"n", kind="notedata", attrs={"title": "计划"})
        project = kernel.store(b"p", kind="projectdata", attrs={"title": "计划"})

        found = kernel.reindex().find_any("title", "计划")

        assert sorted(found) == sorted([note.value_uuid, project.value_uuid])


def test_attributes_lists_what_is_queryable(tmp_path: Path):
    """表能说出"可以按什么查"——界面拿它显示可选条件。"""

    class NoteData(Block):
        """标题可查、标签不查的测试类型。"""

        __table__ = "notedata"

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.title = attr(default="", indexed=True)
            self.tags = attr(factory=dict[str, int])

    with Kernel.create(tmp_path / "vault") as kernel:
        kernel.store(b"b1", kind="notedata", attrs={"title": "t", "tags": {"a": 1}})

        assert kernel.reindex().attributes == (("notedata", "title"),)


# ---- 只是派生：查不到的三种情形 ----


def test_undeclared_attributes_are_not_indexed(tmp_path: Path):
    """没有声明要查的属性不进表：领域只为自己要用的那几条付代价。"""

    class NoteData(Block):
        """只声明标题可查的测试类型。"""

        __table__ = "notedata"

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.title = attr(default="", indexed=True)
            self.author = attr(default="")

    with Kernel.create(tmp_path / "vault") as kernel:
        kernel.store(b"b1", kind="notedata", attrs={"title": "t", "author": "甲"})

        assert kernel.reindex().find("notedata", "author", "甲") == ()


def test_deleted_blocks_are_not_in_the_index(tmp_path: Path):
    """删掉的块不在表里：记录还在盘上，但它已经不活着了（判据以索引行为准）。"""

    class NoteData(Block):
        """标题可查的测试类型。"""

        __table__ = "notedata"

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.title = attr(default="", indexed=True)

    with Kernel.create(tmp_path / "vault") as kernel:
        keep = kernel.store(b"b1", kind="notedata", attrs={"title": "留下"})
        gone = kernel.store(b"b2", kind="notedata", attrs={"title": "删掉"})
        kernel.drop(gone.value_uuid)

        table = kernel.reindex()

        assert table.find("notedata", "title", "删掉") == ()
        assert table.find("notedata", "title", "留下") == (keep.value_uuid,)


def test_a_block_without_that_attribute_is_skipped(tmp_path: Path):
    """块没给那个属性：它不进表，也不报错。"""

    class NoteData(Block):
        """标题可查的测试类型。"""

        __table__ = "notedata"

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.title = attr(default="", indexed=True)

    with Kernel.create(tmp_path / "vault") as kernel:
        kernel.store(b"b1", kind="notedata")

        assert kernel.reindex().find("notedata", "title", "") == ()


def test_int_and_bool_do_not_collide(tmp_path: Path):
    """`1` 与 `True` 在 Python 里相等，查表不能把它们当成同一个值。"""

    class Counter(Block):
        """数值可查的测试类型。"""

        __table__ = "counter"

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.count = attr(default=0, indexed=True)

    with Kernel.create(tmp_path / "vault") as kernel:
        one = kernel.store(b"b1", kind="counter", attrs={"count": 1})

        found = kernel.reindex().find("counter", "count", True)

        assert found == (), "布尔与整数是两回事"
        assert kernel.reindex().find("counter", "count", 1) == (one.value_uuid,)


# ---- 声明写坏了当场报 ----


def test_indexing_an_unknown_attribute_is_refused():
    """声明要查的属性不在这个类型上：登记期报错，不静默留个永远空着的条件。

    可查与否写在属性自己的声明上（`attr(..., indexed=True)`），故块那一侧已经写不出
    "查一个不存在的属性"；这条判据仍在**登记表**那一层把守，由它兜住手写的登记。
    """

    with pytest.raises(TableDeclarationError, match="不是它的属性"):
        REGISTRY.register(
            TypeDecl(
                name="Broken",
                table="broken",
                attrs=(("title", TypeSpec(str)),),
                indexed=("没有这个",),
            )
        )


def test_indexing_a_container_is_refused():
    """容器属性不可查：值不可哈希，按它查只能是"包含"式。

    可查与否写在属性自己的声明上（`indexed=True`），拦的时机随之后移到**登记**那一步——
    探针把形状收上来、登记表照它立表时当场报错，不静默留个永远空着的条件。
    """

    class Bulky(Block):
        """把容器声明成可查的测试类型。"""

        __table__ = "bulky"

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.tags = attr(factory=dict[str, int], indexed=True)

    with pytest.raises(TableDeclarationError, match="容器"):
        declare_type(Bulky)
