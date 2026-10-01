# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""属性契约：声明即登记、登记即落载荷、落载荷即可读回。

这一组钉住"属性跟着块走"这条链的每一段：**`__init__` 里声明 → 登记表 → 块记录载荷 → 读回**。
任何一段断开，本文件都会红。

声明写在 `__init__` 里（`self.title = attr(default="")`），故声明与构造同处一室；
基座在子类的 `__init__` 跑完之后扫一遍实例，把标记收成类型形状，再把标记换成真实默认值。

登记是**进程内**的，故每个用例自带一份干净的登记：内核那两张表按定义处的形状重放，
用例自己定义的类型则在用例里诞生、随用例结束消失（与 `test_tablegen.py` 同一套做法）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cbor2
import pytest

from core.attr import attr
from core.conf.types import TypeSpec
from core.exc import AttrTypeError
from core.init import Kernel
from core.storage.format.block import (
    Block,
    BlockPayload,
    BodyRef,
    block_attrs,
    block_payload_of,
    body_ref_of,
    encode_block_payload,
    install_core_types,
)
from core.storage.format.id import ID
from core.storage.registry import REGISTRY, TypeDecl

if TYPE_CHECKING:
    from collections.abc import Iterator

_REF = BodyRef(value_uuid="u-1", value_hash="h-1")


def _registered(name: str) -> TypeDecl:
    """取一个已登记的类型；没登记就当场失败（用例要的是它一定在）。"""
    decl = REGISTRY.get(name)
    assert decl is not None, name
    return decl


@pytest.fixture(autouse=True)
def clean_registry() -> Iterator[None]:
    """每个用例一份干净的登记，**用完还原**。

    登记是进程内的**全局**状态：本文件在用例里定义的测试类型若留到用例之后，后面的用例
    （比对"入库的声明文件与登记表是否分叉"那几支）会看见它们而误判。故两头都清。
    """
    REGISTRY.clear()
    install_core_types()
    yield
    REGISTRY.clear()
    install_core_types()


# ---- 声明与登记 ----


def test_declaring_attributes_registers_their_types():
    """`self.x = attr(...)` 被登记成属性；其余赋值一个字都不记。"""

    class Notedata(Block):
        """带属性的测试类型。"""

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.title = attr(default="")
            self.tags = attr(factory=dict[str, int])
            self.plain = "不算数"

    decl = _registered("Notedata")

    assert decl.attrs == (("title", TypeSpec(str)), ("tags", TypeSpec(dict, entries=int))), (
        "只有写成 attr(...) 的字段才是属性；普通实例状态不进登记"
    )


def test_attribute_names_are_recorded_in_declaration_order():
    """属性按 `__init__` 里书写的顺序登记，故投影与载荷都可复现。"""

    class Ordered(Block):
        """属性书写顺序有意义的测试类型。"""

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.zebra = attr(default=0)
            self.alpha = attr(default="")

    assert [name for name, _ in _registered("Ordered").attrs] == ["zebra", "alpha"]


def test_attr_without_a_default_is_rejected():
    """`attr()` 既不给默认值也不给工厂：当场报错，不静默当普通字段。"""

    class Bare(Block):
        """漏给缺省值的测试类型。"""

        def __init__(self) -> None:
            super().__init__()
            # 故意一个缺省值都不给：验的是声明期当场报错，故下面那行不必合 mypy 的规矩。
            self.title = attr()  # type: ignore[call-overload]

    with pytest.raises(AttrTypeError, match="要给出缺省值"):
        Bare()


def test_attr_type_outside_the_vocabulary_is_rejected():
    """属性的类型走 `conf` 那套词表：`bytes` 不在其中，声明期就拦下。"""

    class BadType(Block):
        """类型不合词表的测试类型。"""

        def __init__(self) -> None:
            super().__init__()
            self.blob = attr(default=b"", type=bytes)

    with pytest.raises(AttrTypeError, match="不在词表里"):
        BadType()


def test_identity_wins_over_attribute_on_the_same_field():
    """同一个字段先判身份：字段上是 `ID` 即身份，不会再同时成为属性。

    旧范式的判据是**名字**（`value_uuid` 先算身份列）；新范式的判据是**值**
    （字段上是 `ID` 实例即身份）——判据换了，结论不变：先判身份。
    """

    class Clash(Block):
        """身份与属性同处一个字段的测试类型。"""

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.value_uuid = ID()

    decl = _registered("Clash")

    assert decl.attrs == (), "身份字段不会再进属性"
    assert "value_uuid" in decl.ids


# ---- 载荷：属性跟着块走 ----


def test_block_payload_carries_attrs_roundtrip():
    """块载荷带上属性，读回来就是那份映射（含中文与容器）。"""
    raw = encode_block_payload(_REF, {"title": "第一行", "tags": ["a", "b"]})
    parsed = block_payload_of(raw)

    assert parsed is not None
    assert parsed.ref == _REF
    assert parsed.attrs == {"title": "第一行", "tags": ["a", "b"]}


def test_unencodable_attribute_is_rejected():
    """属性值编不进 CBOR：当场报错，不写半条记录。"""
    with pytest.raises(AttrTypeError, match="编不进载荷"):
        encode_block_payload(_REF, {"bad": object()})


def test_block_without_attrs_reads_back_as_empty():
    """没有声明过属性的块不带那个键，读回来是空映射（不是报错）。"""
    raw = encode_block_payload(_REF)

    assert _attrs_absent(raw), "空属性不该写进载荷"
    parsed = block_payload_of(raw)
    assert parsed is not None
    assert parsed.attrs == {}
    assert body_ref_of(raw) == _REF, "只取指针的老入口照旧可用"


def test_content_payload_is_still_not_a_block():
    """一份形如 `{value_uuid, value_hash}` 的普通正文不会被误判成块载荷。

    判据是**保留键带不可打印前缀**：业务数据写不出那个键，故它认不错。
    """
    plain = cbor2.dumps(_REF.to_record(), canonical=True)

    assert block_payload_of(plain) is None


def _attrs_absent(raw: bytes) -> bool:
    """载荷里确实没有属性那个键（对着解码后的映射直接看）。"""
    decoded = cbor2.loads(raw)
    return isinstance(decoded, dict) and "\x00cairn.attrs" not in decoded


# ---- 从实例取值 ----


def test_block_attrs_takes_only_declared_fields():
    """`block_attrs` 只取登记里有的字段：没声明的字段不进载荷。"""

    class Notedata(Block):
        """带裸字段的测试类型。"""

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.title = attr(default="标题")
            self.plain = "不算数"

    note = Notedata()

    assert block_attrs(note) == {"title": "标题"}


def test_block_attrs_is_empty_for_a_type_without_attributes():
    """一个属性都没有的类型取出来就是空映射。"""

    class Bare(Block):
        """没有任何属性的测试类型。"""

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()

    assert block_attrs(Bare()) == {}


# ---- 内核闭环 ----


def test_store_then_read_back_attrs(tmp_path):
    """存一个带属性的块，再把属性读回来：这是本次打通的那条链。"""

    class Notedata(Block):
        """闭环用的测试类型。"""

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.title = attr(default="")
            self.tags = attr(factory=dict[str, int])

    with Kernel.create(tmp_path) as kernel:
        note = Notedata()
        note.title = "第一篇"
        note.tags = {"a": 1}
        kid = kernel.store(b"body-bytes", kind="notedata", attrs=block_attrs(note))

        payload = kernel.storage.block_payload(kid.value_uuid)
        assert isinstance(payload, BlockPayload)
        assert payload.attrs == {"title": "第一篇", "tags": {"a": 1}}
        assert kernel.load(kid.value_uuid) == b"body-bytes", "body 那一侧照旧读得回来"


def test_same_body_with_different_attrs_makes_two_blocks(tmp_path):
    """块身份随载荷：同内容配不同属性是两个块，而 body 仍只存一份。"""

    with Kernel.create(tmp_path) as kernel:
        first = kernel.store(b"same-body", attrs={"title": "甲"})
        second = kernel.store(b"same-body", attrs={"title": "乙"})

        assert first.value_uuid != second.value_uuid
        one = kernel.storage.block_payload(first.value_uuid)
        two = kernel.storage.block_payload(second.value_uuid)
        assert one is not None
        assert two is not None
        assert one.ref.value_hash == two.ref.value_hash, "内容面按地址去重，只存了一份"


def test_reading_attrs_of_a_missing_block_is_none(tmp_path):
    """按一个不存在的块身份取载荷：返回 `None`，不抛。"""
    with Kernel.create(tmp_path) as kernel:
        assert kernel.storage.block_payload("没有这个块") is None


def test_declared_attribute_type_is_visible():
    """属性字段的可见类型是它声明的那个（`attr(default=…)` 的重载直接给出）。

    这一行在 mypy strict 下就是判据：类型推不出默认值的类型时，`Notedata().title`
    赋给 `str` 会当场报错。
    """

    class Notedata(Block):
        """可见类型判据用的测试类型。"""

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()
            self.title = attr(default="")

    visible: str = Notedata().title

    assert visible == ""
