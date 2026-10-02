# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""存储引擎的类型工具：`Attr` 与 `Body`——**可索引的声明**（`ID` 在 `db/id.py`）。

**先分清两件事**，本模块只管第二件：

| | 谁决定 | 怎么写 |
|---|---|---|
| **落盘** | 写了就落 | `self.title = ""`、`self.lines = []` —— 忠实记录 |
| **可索引** | 显式声明 | `title: str = Attr("")`、`lines: list[str] = Body([])` |

- :class:`Attr` —— 这个字段进**反表**：按它的值能查回块。**用了它即进，没有开关**；
- :class:`Body` —— 这个字段进**内容记录**：按内容地址去重，可被反查与引用。同样没有开关；
- **普通赋值** —— 照样落盘，但**拿不到索引加持**：那只是一个内联属性。

"声明了却不索引"是个假问题：不要索引就别声明，裸赋值本来就落盘。

**它们是描述符**，这是本模块最重要的一件事：

    class Note(Block):
        title: str = Attr("")            # 声明在类体上
        lines: list[str] = Body([])

    note.title = "标题"                   # 实例里存的是**裸值**
    assert note.title == "标题"           # 读出来也是裸值

三条语义，缺一条这套写法就不成立：

1. **类体上的声明就是声明**：它描述落点，不是"所有实例共用的一份值"；
2. **实例的值存在实例自己的 `__dict__` 里**（`__set__` 写进去）：故 `note.lines.append(...)`
   改的是**这个实例**的列表——`__get__` 直接交还那个对象，就地增改原样生效，
   既不会污染类属性，也不会串到别的实例；
3. **声明活得比赋值更久**：`note.lines = [...]` 只换值，落点由类体上的声明说了算——
   引擎因此任何时候都答得出"这个字段进哪一边"。

**声明放类体、不放 `__init__`**：放进构造里的话，`self.title = Attr("")` 会让这个实例字段的
静态类型变成声明类型，此后 `note.title = "标题"` 与它不符。类体是**字段类型与落点声明同时
成立**的地方。

**`Attr` 不是类型判据**：类型只活在注解里（mypy 用），运行期不认注解。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast, overload

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "ATTR_KIND",
    "BODY_KIND",
    "Attr",
    "Body",
    "declaration_of",
    "kind_of",
    "kinds_of",
    "unwrap",
]

BODY_KIND = "body"
"""落点：这个字段进内容记录。"""

ATTR_KIND = "attr"
"""落点：这个字段是可索引属性（写成 `Attr(...)` 的那道手续）。"""


class _Declaration[T]:
    """声明与值的共用部分：**类体上是声明，实例里是裸值**。

    **为什么用描述符**（"可解释的语法"那一档，理由写在这里）：要的效果是
    `title: str = Attr("")` 在类体上给出声明、而 `note.title` 交出 `str`。不用描述符就只有
    两条路——把声明塞进 `__init__`（那字段的静态类型会变成声明类型，`note.title = "标题"`
    与它不符），或让 `Attr` 冒充成值（那 `note.title` 拿到的是声明对象，不是值）。两条都更差。

    做法是标准的描述符协议：`__set__` 把值写进**实例自己的** `__dict__`，`__get__` 直接
    把那个对象交还。故就地增改（`note.lines.append(...)`）改的是这个实例的那一份，
    既不会污染类属性，也不会串到别的实例。

    两个槽位**写单下划线，不写双下划线**：双下划线会触发名字改写（name mangling），
    而那是本仓不用的一类冷门语法——`__slots__` 里的名字跟着被改写，读的人会看不懂
    "这两个槽到底叫什么"。
    """

    __slots__ = ("_cairn_default", "_cairn_name")

    def __init__(self, value: T) -> None:
        """收下默认值。**它只用于"这个实例还没赋过值"的那一刻**。"""
        self._cairn_default = value
        self._cairn_name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        """记下自己在类体上的名字（`__get__` 按它定位实例里那一份值）。

        `__set_name__` 是解释器在**类创建时**自动调的（PEP 487）：不靠它的话，
        就得自己去 `cls.__dict__` 里反查"哪个名字挂着这个描述符"——那才是猜。
        """
        del owner
        self._cairn_name = name

    @overload
    def __get__(self, instance: None, owner: type | None = ...) -> _Declaration[T]: ...

    @overload
    def __get__(self, instance: object, owner: type | None = ...) -> T: ...

    def __get__(self, instance: object | None, owner: type | None = None) -> _Declaration[T] | T:
        """取值：**实例上取到的是值本身，类上取到的是这个声明**。

        实例还没赋过值就先**现拷一份默认值**。这一步不能省：类体上那个列表是**共享的**，
        直接交还它的话，`first.lines.append(...)` 会改到所有实例（连类属性一起改）。
        标量不可变，拷不拷都一样，故一律走同一条路。
        """
        del owner
        if instance is None:
            return self
        store = vars(instance)
        if self._cairn_name not in store:
            store[self._cairn_name] = _fresh(self._cairn_default)
        return cast("T", store[self._cairn_name])

    def __set__(self, instance: object, value: T) -> None:
        """赋值：写进**实例自己的** `__dict__`。声明因此活得比任何一次赋值更久。"""
        vars(instance)[self._cairn_name] = value

    @property
    def default(self) -> T:
        """类体上写下的那个默认值。"""
        return self._cairn_default

    def __repr__(self) -> str:
        """诊断用：看得出它是哪一类声明，以及它的默认值。"""
        return f"{type(self).__name__}({self._cairn_default!r})"


class Attr[T](_Declaration[T]):
    """**可索引**的块属性：按它的值能反查回块。

    写成 `Attr(...)` 就是"要按它查"那道明确的手续——**用了它必然进反表**。
    不要索引就别用它：裸赋值照样落盘，那不是"声明了却不索引"，而是根本没声明。

    只对标量有意义：容器不可哈希，按它查只能是"包含"式。
    """

    __slots__ = ("doc",)

    def __init__(self, value: T, *, doc: str = "") -> None:
        """收下默认值与说明文本。

        Args:
            value: 字段的默认值。
            doc: 说明文本（给人看；不参与任何落盘或索引判据）。
        """
        super().__init__(value)
        self.doc = doc


class Body[T](_Declaration[T]):
    """进**内容记录**的值：按内容地址去重的那一份（大头正文）。

    **不带 ID 是刻意的**：内容的身份是算出来的摘要（按内容寻址），不靠另签一个身份——
    若内容也各持一个 ID，同内容两次落盘会是两个身份，去重就无从谈起。
    """

    __slots__ = ()


def _fresh[T](value: T) -> T:
    """把默认值取一份：容器现拷，标量原样。

    **类体上的默认值是共享的**，故实例第一次取值时必须拷一份——否则
    `first.lines.append(...)` 会改到类属性，串到所有实例上去。
    """
    if isinstance(value, list):
        return cast("T", list(value))
    if isinstance(value, dict):
        return cast("T", dict(value))
    if isinstance(value, set):
        return cast("T", set(value))
    return value


def unwrap(value: object) -> object:
    """把声明拆掉：`Attr` / `Body` 交出自己的默认值，其余原样返回。

    实例上的字段本来就是裸值，故这个方法主要用于**类体上的声明**。
    """
    if isinstance(value, _Declaration):
        return value.default
    return value


def declaration_of(cls: type[object], name: str) -> _Declaration[Any] | None:
    """这个字段在类体上的声明；没有即 ``None``（那它是普通赋值）。"""
    for klass in cls.__mro__:
        member = klass.__dict__.get(name)
        if isinstance(member, _Declaration):
            return member
    return None


def kind_of(cls: type[object], name: str) -> str:
    """一个字段的落点：`'body'` / `'attr'` / `''`（普通赋值）。

    **从类体上读**，故与"实例里那个值现在是什么"无关——声明活得比赋值更久。
    """
    member = declaration_of(cls, name)
    if isinstance(member, Body):
        return BODY_KIND
    if isinstance(member, Attr):
        return ATTR_KIND
    return ""


def kinds_of(cls: type[object]) -> dict[str, str]:
    """这个类型声明了哪些落点：字段名 → `'body'` / `'attr'`（子类覆盖父类）。

    顺序按**声明处的书写顺序**：MRO 由远及近铺一遍，同名以子类为准。
    """
    found: dict[str, str] = {}
    for klass in reversed(cls.__mro__):
        for name, member in klass.__dict__.items():
            if isinstance(member, Body):
                found[name] = BODY_KIND
            elif isinstance(member, Attr):
                found[name] = ATTR_KIND
    return found


def declarations_of[T: _Declaration[Any]](
    cls: type[object], kind: type[T]
) -> Iterator[tuple[str, T]]:
    """这个类上某一类声明的（字段名，声明）序列，按声明处的书写顺序。"""
    seen: dict[str, T] = {
        name: member
        for klass in reversed(cls.__mro__)
        for name, member in klass.__dict__.items()
        if isinstance(member, kind)
    }
    yield from seen.items()
