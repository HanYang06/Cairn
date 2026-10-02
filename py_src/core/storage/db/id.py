# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""ID：接口的那一半，也是索引之所以存在的那一半。

**ID 属于数据库这一侧**（故它与 `db/` 同族，不在 storage 根下）。理由不是"实现方便"，
而是它的作用就是这个：**ID 是索引的来路**。

- **用了 ID，库里就产生一张真正意义上的索引表**（表名取自 ID 的名字）；
- **不用 ID，那张表自然不产生**——那个类只是活在别处载荷里的结构，不登记、不建表。

故库的结构没有第二条来路：一个类型一张身份表，列就是 ID 的字段。

**两套凭证并存，不取其一**：

- `value_uuid`：签发时分配，与内容无关——比较有效、去重无效。它使"同内容的两次落盘"
  仍可区分与引用；
- `value_hash`：由内容算出——去重有效、比较无效。它使同内容判同、使索引能在盘上
  反过来找到"这份内容"。

**可变是局部的，而且可变的字段数得出来**：

| 字段 | 何时定 | 之后 |
|---|---|---|
| `value_uuid` / `birth_time` | **创建那一刻** | 锁死（只读属性） |
| `value_hash` | **内容算出来那一刻** | 锁死；只有 :meth:`ID.bind` 一条路能写进去 |
| `name` | 由持有者解析出来那一刻 | 锁死（它由持有者定，没有"之后改"的正当理由） |
| `in_hub` / `in_hub_pack` / `in_pack_slot` | 写完回填 | **可改**——它们是投影，压实搬移后重算即得 |

前三项是"这个身份是谁、什么时候生的、内容是哪份"——**改一个字节即另一个身份**，
故一律锁死；位置段是"它现在躺在哪"——**本来就会变**，故不锁。

故本类**不用 dataclass**：它要的是"三个只读 + 一个受控写入 + 三个可写"，而 dataclass 只能
全可变或全冻结。冻结同样不成：`__init__` 里在字段声明处就要读它的内部值（派生字段），
而那一刻摘要还没绑。
"""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import uuid4

from core.clock import now_ns
from core.exc import InvalidIdError

if TYPE_CHECKING:
    from collections.abc import Mapping

EMPTY_HASH = ""
"""未绑定内容时的摘要形态：**空串**，不得用随机值冒充。"""

EMPTY_SPAN: tuple[int, int] = (0, 0)
"""未落盘时的格区间：两格号都是零。"""

_UNBOUND = "未绑定内容"
"""报错里对"摘要为空"的写法，免得读者以为那是某个内容算出来的值。"""


def new_uuid() -> str:
    """签发一个新的唯一标识形态凭证：与内容无关，每次调用均得新值。"""
    return str(uuid4())


def digest(data: bytes) -> str:
    """按内容算出摘要形态凭证（小写十六进制）：同内容同值，内容变则值变。"""
    return sha256(data).hexdigest()


class ID:
    """系统级富信息 ID：身份与位置。

    **它是身份本身**，不是一个"指向身份的句柄"：拿它就等于拿到了两套凭证与签发时刻。
    签发它只需要一个持有者，名字从持有者推出来：

        self.id = ID(self)          # → name = "notedata"

    **只记名字，不持有那个对象**：`obj → id → obj` 会成环，块永远回收不掉。

    Attributes:
        name: 可读名称，由持有者推出；**表名取自它**。给持有者对象或给名字字符串都认。
        value_uuid: 分配形态凭证。**创建后只读**。
        value_hash: 摘要形态凭证；由内容算出。**创建后只读**，写入只有 `bind` 一条路。
        birth_time: 该 ID 被签发的时刻（unix 纳秒）。**创建后只读**；
            不等于块或数据的创建时间。
        in_hub: 所在 hub（目录名）。**可写**：它是投影，写入后回填。
        in_hub_pack: hub 内的载体。**可写**。
        in_pack_slot: 载体内的格区间（头格，末格），闭区间。**可写**。
    """

    __slots__ = (
        "_birth_time",
        "_name",
        "_value_hash",
        "_value_uuid",
        "in_hub",
        "in_hub_pack",
        "in_pack_slot",
    )

    def __init__(
        self,
        holder: object = "",
        *,
        value_uuid: str = "",
        birth_time: int | None = None,
    ) -> None:
        """签发一个 ID：名字从 `holder` 推出来，两个凭证当场定死。

        Args:
            holder: 持有者（`ID(self)`）或其名字（`ID("notedata")`）。
            value_uuid: 分配形态凭证；不给即现签一个。**给它是为了从记录还原**。
            birth_time: 签发时刻（unix 纳秒）；不给即取当前。**给它是为了从记录还原**。

        Raises:
            InvalidIdError: 分配形态凭证为空（空串是"没有身份"，不是"待补"）。
        """
        self._name = _resolved_name(holder)
        self._value_uuid = value_uuid or new_uuid()
        if not self._value_uuid:
            raise InvalidIdError("分配形态凭证不能为空")
        self._birth_time = now_ns() if birth_time is None else int(birth_time)
        self._value_hash = EMPTY_HASH
        self.in_hub = ""
        self.in_hub_pack = ""
        self.in_pack_slot = EMPTY_SPAN

    # ---- 锁死的四项 ---- #

    @property
    def name(self) -> str:
        """名字：由持有者推出，**之后不可改**（表名取自它）。"""
        return self._name

    @property
    def value_uuid(self) -> str:
        """分配形态凭证：签发时定，**之后不可改**。"""
        return self._value_uuid

    @property
    def birth_time(self) -> int:
        """该 ID 被签发的时刻：**之后不可改**。"""
        return self._birth_time

    @property
    def value_hash(self) -> str:
        """摘要形态凭证：**创建后只读**，写入只有 :meth:`bind` 一条路。"""
        return self._value_hash

    # ---- 签发 ---- #

    @classmethod
    def of(cls, data: bytes, *, name: object = "") -> ID:
        """**按内容签发**：摘要形态由 `data` 算出，分配形态与内容无关。

        内容的身份就从这里来：同内容恒得同一个 `value_hash`，故去重成立。
        """
        identity = cls(name)
        identity.bind(data)
        return identity

    @classmethod
    def unbound(cls, *, name: object = "") -> ID:
        """签发一个**还没绑定内容**的身份：只有分配形态与签发时刻。"""
        return cls(name)

    def bind(self, data: bytes, *, rebind: bool = False) -> str:
        """把内容摘要绑到这个身份上，返回算出的摘要。**这是写摘要的唯一通路。**

        **只许绑一次**：摘要一旦写下就是那个身份的一部分。重复绑定同一份内容
        是同一件事的重放，放过；换成别的内容即说明一份身份指了两份内容，当场报错。

        例外的唯一入口是 `rebind=True`，**它只给引擎用**：同一个块改了字段再存一次，
        块身份随载荷而变，那份摘要本来就该换。调用方不该碰这个开关——它是"引擎在维护
        它自己算出来的那一项"，不是"用户可以改身份"。

        Args:
            data: 内容字节。
            rebind: 允许改绑（引擎重写同一个块时用）。

        Raises:
            InvalidIdError: 这个身份已经绑定了别的内容，且没有开 `rebind`。
        """
        computed = digest(data)
        if self._value_hash:
            if not rebind and self._value_hash != computed:
                raise InvalidIdError(
                    f"ID 已绑定了别的内容: {self._value_hash[:12]}…，"
                    f"本次算出 {computed[:12]}…（摘要写定即不可改）"
                )
            self._value_hash = computed
            return computed
        self._value_hash = computed
        return computed

    # ---- 问 ---- #

    @property
    def bound(self) -> bool:
        """是否已绑定内容。"""
        return bool(self._value_hash)

    @property
    def located(self) -> bool:
        """是否已写上物理坐标（hub 与载体都有值）。"""
        return bool(self.in_hub) and bool(self.in_hub_pack)

    def same_content(self, other: ID) -> bool:
        """两者是否指向同一份内容：**只比摘要形态**，未绑定内容者恒不相等。"""
        return self.bound and self._value_hash == other._value_hash

    # ---- 落盘 ---- #

    def to_record(self) -> dict[str, object]:
        """**落盘的那部分 ID**：索引库里有的身份字段，都要能从记录还原。

        带两套凭证、名字与签发时刻；**位置段不带**——记录在哪儿由"它是在哪个载体的哪一格
        被扫到"给出，扫一遍即可重建，故不必占记录头。
        """
        return {
            "name": self.name,
            "value_uuid": self._value_uuid,
            "value_hash": self._value_hash,
            "birth_time": self._birth_time,
        }

    @classmethod
    def from_record(cls, raw: Mapping[str, object]) -> ID:
        """由落盘子集还原 ID：三个锁死的字段从记录取回，位置段留空（它是投影）。

        **写只写必需，读尽量读回**：分配形态必须有（它是这份身份的唯一性所在）；
        摘要**允许为空**——记录的身份不必与内容摘要重合（内容记录按载荷摘要寻址，
        它自己那份身份是分配形态），把摘要从这里读成空只是"这份身份没绑内容"。
        未知的整数字段形态非法即抛，不静默吞掉脏字节。**不伪造签发时间**：未知一律取零。

        Raises:
            InvalidIdError: 分配形态凭证缺失或为空，或整数字段形态非法。
        """
        try:
            value_uuid = str(raw["value_uuid"] or "")
        except (KeyError, TypeError) as error:
            raise InvalidIdError(f"ID 记录缺少必需字段: {raw!r}") from error
        if not value_uuid:
            raise InvalidIdError(f"ID 记录缺分配形态凭证: {raw!r}")
        identity = cls(
            str(raw.get("name") or ""),
            value_uuid=value_uuid,
            birth_time=_int_or_zero(raw.get("birth_time")),
        )
        content = str(raw.get("value_hash") or "")
        if content:
            identity._value_hash = content  # 还原即"确认这份摘要"，等价于 bind 那一次写入
        return identity

    def __repr__(self) -> str:
        """诊断用：名字、两个凭证的前一段，以及位置（若已落盘）。"""
        content = self._value_hash[:12] if self.bound else _UNBOUND
        where = "-"
        if self.located:
            where = f"{self.in_hub}/{self.in_hub_pack}{list(self.in_pack_slot)}"
        return f"ID(name={self.name!r}, uuid={self._value_uuid[:8]}…, hash={content}, at={where})"


ID_FIELDS: tuple[str, ...] = (
    "name",
    "value_uuid",
    "value_hash",
    "birth_time",
    "in_hub",
    "in_hub_pack",
    "in_pack_slot",
)
"""`ID` 的**全部**字段名，顺序即声明顺序。

索引库里的身份列照这份清单逐列搬：谁用了 ID，那张表就有这几列，一个不多、一个不少。
故"某个字段进不去库"在代码上不成立——清单是从 `ID` 上数出来的，不是另抄一份子集。
"""


def _resolved_name(holder: object) -> str:
    """把持有者解析成名字：**`ID(self)` 是最省事的写法**。

    `self` 是持有者，也是写的人在 `__init__` 里唯一确定持有的东西；名字从它推出来，
    故不必在每个类里把类名再写一遍。传类（`ID(NoteData)`）得到同一个答案，两条路一致。
    传字符串即照用（从记录还原走这条）。
    """
    if isinstance(holder, str):
        return holder
    resolved = getattr(holder, "__name__", None)
    if resolved is None:
        resolved = type(holder).__name__
    return str(resolved).lower()


def _int_or_zero(value: object) -> int:
    """把可选整数字段读回：缺失取 0，形态非法即抛（不静默吞掉脏字节）。"""
    if value is None:
        return 0
    try:
        return int(str(value))
    except ValueError as error:
        raise InvalidIdError(f"ID 记录的整数字段非法: {value!r}") from error


__all__ = [
    "EMPTY_HASH",
    "EMPTY_SPAN",
    "ID",
    "ID_FIELDS",
    "digest",
    "new_uuid",
]
