# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""块与载荷契约：声明写在 `__init__` 里，身份可有可无。

新范式的三条口径在这里钉住：

- `Block` 是**基座**不是泛型壳：`Block()` 不带身份、`Block(id=…)` 带身份，
  子类一被定义就由 `__init_subclass__` 接管；
- 字段声明（`attr` / `Body`）写在 `__init__` 里，跑完那一遍之后实例上留下的是
  **真实默认值**（`""` / `[]`），不是声明标记；
- **有 `self.id = ID()` 才有表**：没有它的类型是只活在载荷里的结构，不登记、不建表。

形状由**零参探针**现算，故每个块的 `__init__` 都必须能零参调用。
"""

from __future__ import annotations

import pytest

from core.attr import attr
from core.exc import AttrTypeError, BlockShapeError
from core.storage.format.block import Block, Body, BodyDecl, declare_type, install_core_types
from core.storage.format.id import ID
from core.storage.registry import REGISTRY


@pytest.fixture(autouse=True)
def clean_registry():
    """每个用例一份干净的登记表：形状是探出来的，上一个用例留的形状不该影响下一个。"""
    REGISTRY.clear()
    install_core_types()
    yield
    REGISTRY.clear()
    install_core_types()


# ---- 构造语义：身份可选 ----


def test_the_base_block_issues_no_identity_by_itself():
    """`Block()` 不带身份：基座不替调用方签发 ID，故它没有 `id` 这个字段。"""
    plain = Block()

    assert "id" not in vars(plain), "没有 ID 的块不产生表，也就不该有身份字段"


def test_the_base_block_takes_an_identity_when_one_is_given():
    """`Block(id=…)` 带身份：给了就原样收下，不另签发一个。"""
    given = ID()

    assert Block(id=given).id == given


# ---- 声明 → 真实默认值 ----


def test_a_declaration_becomes_the_real_default_on_the_instance():
    """声明跑完即换成真实默认值：实例上的 `title` 是字符串、`lines` 是列表。"""

    class Notedraft(Block):
        """带属性与载荷的测试类型。"""

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.title = attr(default="")
            self.lines: list[str] = Body(factory=list)

    note = Notedraft()

    assert note.title == ""
    assert note.lines == []
    assert not isinstance(note.lines, BodyDecl), "实例上留下的是默认值，不是声明标记"


def test_two_instances_do_not_share_a_declared_payload_list():
    """两个实例不共用同一个载荷列表：声明只定形状，值每个实例各造一份。"""

    class Twolists(Block):
        """带载荷的测试类型。"""

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.lines: list[str] = Body(factory=list)

    first, second = Twolists(), Twolists()
    first.lines.append("一")

    assert first.lines is not second.lines
    assert second.lines == []


def test_mutable_literal_defaults_are_copied_per_instance():
    """可变的**字面**缺省值在实例之间也不串：写成 `default=[]` 时每次拷一份。"""

    class Mutablebox(Block):
        """带可变字面缺省值的测试类型。"""

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.tags: list[str] = attr(default=[])
            self.lines: list[str] = Body(default=[])

    first, second = Mutablebox(), Mutablebox()
    first.tags.append("一")
    first.lines.append("行")

    assert first.tags is not second.tags
    assert first.lines is not second.lines
    assert second.tags == []
    assert second.lines == []


# ---- 登记：有 ID 才有表 ----


def test_only_a_type_that_declares_an_id_is_registered():
    """有 `self.id = ID()` 才有表：没有它的类型是只活在载荷里的结构，不登记。"""

    class Markednote(Block):
        """持有身份的类型。"""

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()

    class Unmarkednote(Block):
        """不持有身份的结构。"""

        def __init__(self) -> None:
            super().__init__()
            self.title = attr(default="")

    assert REGISTRY.get("Markednote") is not None
    assert REGISTRY.table("markednote") is not None
    assert REGISTRY.get("Unmarkednote") is None
    assert declare_type(Unmarkednote) is None, "没声明 ID 的类型交不出登记"


def test_a_shape_probe_requires_a_zero_argument_init():
    """形状由零参探针现算：`__init__` 要参数的类型探不出形状，当场报错。"""

    class Needsargument(Block):
        """`__init__` 带参数的测试类型。"""

        def __init__(self, title: str) -> None:
            super().__init__()
            self.id = ID()
            self.title = title

    with pytest.raises(BlockShapeError, match="零参"):
        declare_type(Needsargument)


# ---- 继承：父类的声明跟着下来 ----


def test_a_subclass_keeps_the_parent_declarations():
    """子类声明的形状 = 父类那几个 + 自己那几个，值也都在。

    判据不是形式：基座逐层包 `__init__`，内层那一遍**已经把标记换成真实默认值**，
    故收货只能**并**、不能重扫覆盖——否则子类会把父类的字段悄悄丢干净。
    """

    class Baseentry(Block):
        """父类型：一个属性、一条载荷。"""

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.title = attr(default="")
            self.lines: list[str] = Body(factory=list)

    class Childentry(Baseentry):
        """子类型：在父类之后再加一个属性。"""

        def __init__(self) -> None:
            super().__init__()
            self.extra = attr(default=0)

    decl = REGISTRY.get("Childentry")
    assert decl is not None
    assert [name for name, _ in decl.attrs] == ["title", "extra"]
    assert decl.payload == ("lines",)

    child = Childentry()
    assert child.title == ""
    assert child.lines == []
    assert child.extra == 0


def test_a_subclass_without_its_own_init_still_inherits_declarations():
    """只继承、不重写 `__init__` 的子类：父类那一层照跑，字段与值都在。"""

    class Silentbase(Block):
        """父类型：一个属性。"""

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.title = attr(default="")

    class Silentchild(Silentbase):
        """子类型：整份继承，不写 `__init__`。"""

    decl = REGISTRY.get("Silentchild")
    assert decl is not None
    assert [name for name, _ in decl.attrs] == ["title"]
    assert Silentchild().title == ""


# ---- 载荷声明是标记，不是容器 ----


def test_a_body_declaration_is_a_marker_not_a_container():
    """`Body(...)` 是**载荷声明标记**：返回 `BodyDecl`，每问一次现造一份缺省值。"""
    declaration: object = Body(default=[])

    assert isinstance(declaration, BodyDecl)
    assert declaration.make() == []
    assert declaration.make() is not declaration.make(), "可变缺省值一次一份"


def test_a_body_declaration_takes_exactly_one_default_source():
    """载荷声明的缺省值只能有一个出处：一个都不给、或两样都给，都当场报错。"""
    with pytest.raises(BlockShapeError, match="缺省值"):
        Body()  # type: ignore[call-overload]
    with pytest.raises(BlockShapeError, match="缺省值"):
        Body(default=[], factory=list)  # type: ignore[call-overload]


def test_an_attribute_declaration_takes_exactly_one_default_source():
    """属性声明同一条规矩：缺省值给重了或一个都没给，报 `AttrTypeError`。"""
    with pytest.raises(AttrTypeError, match="缺省值"):
        attr()  # type: ignore[call-overload]
    with pytest.raises(AttrTypeError, match="缺省值"):
        attr(default=0, factory=int)  # type: ignore[call-overload]
