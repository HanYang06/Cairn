# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""ID:身份本身,也是索引之所以存在的那一半.

**ID 属于数据库这一侧**(故它与 `db/` 同族,不在 storage 根下).理由不是"实现方便",
而是它的作用就是这个:**ID 是索引的来路**.

- **用了 ID,库里就产生一张真正意义上的身份表**(表名取自 ID 的名字);
- **不用 ID,那张表自然不产生**——那个类只是活在别处载荷里的结构,不登记,不建表.

故库的结构没有第二条来路:一个类型一张身份表,列就是 ID 的字段加正文摘要一列.

**坐标系的分辨**(2026-10-02 修正裁定):**槽号只在 pack 内有意义**,故"越 pack(甚至越 hub)
的关联只能用摘要,不能用槽号".槽这个层级从来没有"出 pack 再关联 ID"这件事:一个块的身份
跨 pack,跨 hub 成立,而它占的槽号只在它那一份载体里成立.故正文关联走摘要(`body` 那一列),
位置走库里的行.

**正文只有当前一份**(2026-10-06 裁定):库里那一列是**一个摘要**,不是摘要链,也不留世代
——存储只做"记录与修改",历史,回滚与安全由上层自行解决.

**身份与位置分工不同,故可变性也不同**:

| 字段 | 何时定 | 之后 |
|---|---|---|
| `value_uuid` | **创建那一刻**(`uuid4()`) | 锁死(只读属性) |
| `birth_time` | **创建那一刻**(unix 纳秒) | 锁死(只读属性) |
| `name` | 由持有者解析出来那一刻 | 锁死 |
| `in_hub` / `in_hub_pack` / `in_pack_slot` | 写完由库记下 | **可改**——位置段是真源,改一次写一次 |

前三项是"这个身份是谁,什么时候生的"——**改一个字节即另一个身份**,故一律锁死;
位置段是"它现在躺在哪"——**本来就会变**,故不锁.

**摘要形态不属于身份**:按内容判同由 `BodyIndex` 负责(2026-10-02 存储裁定).
`digest()` 因此退成模块级函数,只服务正文那一侧;`value_hash` 连同 `ID.of` / `ID.bind` /
`ID.bound` / `ID.same_content` 一并退役.

**位置段是段列表**:元素为"单格一个整数"或"连续一段(起,止)".规范形四条——
升序,不重叠,相邻合并,段数最少.位置段编成段列表文本;正文那一列就是摘要本身
(小写十六进制 ASCII),不必再包一层.

故本类**不用 dataclass**:它要的是"三项只读 + 三项可写",而 dataclass 只能全可变或全冻结.
"""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import uuid4

from core.clock import now_ns
from core.exc import InvalidIdError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

SlotSpan = int | tuple[int, int]
"""位置段的元素：单格记一个整数，连续的一段记一个（起，止）二元组。"""

BODY_FIELD = "body"
"""库里那一列**正文摘要的列名**：位置段之外的第二样真源，`ID` 上没有它。

它装的是**当前那一份正文的摘要**（一个，不是一串）；这个块没有正文即空串。
读它走 :func:`parse_body`，写它就是摘要本身。
"""

DIGEST_LENGTH = 64
"""摘要的文本长度：sha256 的十六进制写法（本报只写小写）。"""

_HEX_DIGITS = frozenset("0123456789abcdef")

EMPTY_SEGMENTS: tuple[SlotSpan, ...] = ()
"""未落盘时的段列表：一个槽都不占。"""

_RANGE_SEP = "-"
_ITEM_SEP = ","


def new_uuid() -> str:
    """签发一个新的唯一标识形态凭证:与内容无关,每次调用均得新值."""
    return str(uuid4())


def digest(data: bytes) -> str:
    """按内容算出摘要(小写十六进制):同内容同值,内容变则值变.

    **它只服务正文那一侧**:写入前按它查 `BodyIndex`(正文位置表),
    载入时按它定位别处的正文;身份不由它决定.
    """
    return sha256(data).hexdigest()


def canonical_segments(spans: Iterable[SlotSpan]) -> tuple[SlotSpan, ...]:
    """把任意段列表归成规范形:**升序,不重叠,相邻合并,段数最少**.

    两条合并判据都作用在同一件事上:单格与区间可以互换,故 `(3, 3)` 与 `3` 是同一格,
    而 `3` 与 `4` 相邻即并成 `(3, 4)`.归完之后"同一批槽"只有一种写法——
    这正是位置段能当判据用的前提.

    Args:
        spans: 任意次序,任意形态的段.

    Returns:
        规范形段列表.

    Raises:
        InvalidIdError: 出现负格号,或区间的止小于起.
    """
    ranges: list[tuple[int, int]] = []
    for item in spans:
        first, last = _bounds(item)
        ranges.append((first, last))
    merged: list[tuple[int, int]] = []
    for first, last in sorted(ranges):
        if merged and first <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], last))
            continue
        merged.append((first, last))
    return tuple(first if first == last else (first, last) for first, last in merged)


def segments_of(
    single: int | None = None, /, *, span: tuple[int, int] | None = None
) -> list[SlotSpan]:
    """由一个格号或一个闭区间造出规范形段列表(写侧最常用的那两种构造).

    Args:
        single: 单个格号.
        span: 闭区间(起,止).

    Returns:
        规范形段列表.

    Raises:
        InvalidIdError: 两者都不给.
    """
    if single is None and span is None:
        raise InvalidIdError("段列表至少要有一个来源：给一个格号或一个闭区间")
    if single is not None:
        return list(canonical_segments([single]))
    return list(canonical_segments([span]))  # type: ignore[list-item]


def pack_segments(spans: Iterable[SlotSpan]) -> str:
    """把段列表编成文本:**单格写一个数,连续的一段写 `起-止`**,以逗号分隔.

    输入先归成规范形,故编出来的形态只由**那一批槽**决定,与调用方给的写法无关:
    `[1, 2, 6, 8, 9, 10]` 与 `[1, (2, 2), (6, 6), (8, 10)]` 编出同一个答案.
    零散形是合法的,收敛成整段是回收的待办(`gc.sweep`).

    **按次序写**是另一件事(:func:`pack_segments_ordered`):位置段的次序有意义,
    故库里那一列不能用归位之后的形态.
    """
    return _text_of_segments(canonical_segments(spans))


def pack_segments_ordered(slots: Iterable[int]) -> str:
    """把一串槽号按**原次序**编成文本(相邻者并成一段,次序不动).

    它给库里那一列用:位置段的次序有意义(属性槽在前,正文槽在后),
    而按格号归位会把这个次序翻过来.
    """
    return _text_of_segments(_merge_in_order(slots))


def parse_segments(text: str) -> tuple[SlotSpan, ...]:
    """把文本解析成段列表,**保持文本里的次序**.

    认两种形态:`"1,2,6,8-10"`(单格与区间混写)与 `"3:5"`(旧的闭区间写法,
    只为读旧值,不再写出).空串即"一个槽都不占".

    **不归位**:位置段的次序有意义(属性槽在前,正文槽在后),归位会把两次保存之间的
    切分翻过来.要规范形的地方(回收,诊断)另行调 :func:`canonical_segments`.

    Args:
        text: 段列表的文本.

    Returns:
        段列表(次序照文本).

    Raises:
        InvalidIdError: 段落写不成数字,或区间的止小于起.
    """
    raw = text.strip()
    if not raw:
        return EMPTY_SEGMENTS
    if ":" in raw and _ITEM_SEP not in raw:
        head, _, tail = raw.partition(":")
        return (_validated((_as_int(head), _as_int(tail))),)
    spans: list[SlotSpan] = []
    for part in raw.split(_ITEM_SEP):
        item = part.strip()
        if not item:
            raise InvalidIdError(f"段列表里有空项: {text!r}")
        if _RANGE_SEP in item:
            head, _, tail = item.partition(_RANGE_SEP)
            spans.append(_validated((_as_int(head), _as_int(tail))))
            continue
        spans.append(_validated(_as_int(item)))
    return tuple(spans)


def _validated(item: SlotSpan) -> SlotSpan:
    """校验一个段:格号不得为负,区间的止不得小于起."""
    first, last = _bounds(item)
    return first if first == last else (first, last)


def parse_body(text: str) -> str:
    """把库里那一列读成**当前正文的摘要**;空串即这个块没有正文.

    这一层是**位置段之外的第二样真源**:位置段说"这个块自己占哪些槽",
    这一列说"它用的是哪一份正文".

    **只认两种形态**:空串,或一段小写十六进制摘要.其余一律抛——这一列只由
    :func:`digest` 写出,读到别的就是坏值,不静默当成"没有正文".

    Args:
        text: 库里那一列的原样文本.

    Returns:
        摘要;没有正文即空串.

    Raises:
        InvalidIdError: 文本既不是空串,也不是一段摘要.
    """
    raw = text.strip()
    if not raw:
        return ""
    if len(raw) != DIGEST_LENGTH or not _HEX_DIGITS.issuperset(raw):
        raise InvalidIdError(f"正文摘要读不出来: {raw!r}")
    return raw


def _text_of_segments(spans: Iterable[SlotSpan]) -> str:
    """把段列表折成文本:单格写一个数,连续的一段写 `起-止`."""
    parts: list[str] = []
    for item in spans:
        if isinstance(item, int):
            parts.append(str(item))
            continue
        parts.append(f"{item[0]}{_RANGE_SEP}{item[1]}")
    return _ITEM_SEP.join(parts)


def _slots_of_spans(spans: Iterable[SlotSpan]) -> list[int]:
    """把段列表展开成槽号的一串(**保持段列表的次序**)."""
    found: list[int] = []
    for item in spans:
        if isinstance(item, int):
            found.append(item)
            continue
        found.extend(range(item[0], item[1] + 1))
    return found


def _merge_in_order(slots: Iterable[int]) -> list[SlotSpan]:
    """把一串槽号按**原次序**折成段:相邻者并成一段,次序不动."""
    found: list[SlotSpan] = []
    for slot in slots:
        if slot < 0:
            raise InvalidIdError(f"格号不能为负: {slot}")
        if found and isinstance(found[-1], tuple) and found[-1][1] + 1 == slot:
            found[-1] = (found[-1][0], slot)
            continue
        if found and isinstance(found[-1], int) and found[-1] + 1 == slot:
            found[-1] = (found[-1], slot)
            continue
        found.append(slot)
    return found


def _merge_groups(groups: Iterable[Iterable[SlotSpan]]) -> list[SlotSpan]:
    """把若干**分组**的段拼成一份段列表:组内相邻者并段,**组与组之间不并**.

    组的存在只为表达次序(属性槽在前,正文槽在后),不表达"哪一格是什么"——
    那是槽头的事.
    """
    found: list[SlotSpan] = []
    for group in groups:
        found.extend(_merge_in_order(_slots_of_spans(group)))
    return found


def _bounds(item: SlotSpan) -> tuple[int, int]:
    """把一个段拆成闭区间;单格即起止相同."""
    if isinstance(item, bool):  # bool 是 int 的子类,位置段上它不是格号
        raise InvalidIdError(f"段列表的元素不能是布尔: {item!r}")
    if isinstance(item, int):
        if item < 0:
            raise InvalidIdError(f"格号不能为负: {item}")
        return item, item
    if isinstance(item, tuple) and len(item) == 2:
        first, last = int(item[0]), int(item[1])
        if first < 0 or last < 0:
            raise InvalidIdError(f"格号不能为负: {item!r}")
        if last < first:
            raise InvalidIdError(f"区间的止小于起: {item!r}")
        return first, last
    raise InvalidIdError(f"段列表的元素形态不对: {item!r}")


def _as_int(text: str) -> int:
    """把一段文本读成整数;读不出来即抛,不静默取零."""
    try:
        return int(text.strip())
    except ValueError as error:
        raise InvalidIdError(f"段列表里的数字读不出来: {text!r}") from error


class ID:
    """系统级富信息 ID:**身份本身**,不是一个"指向身份的句柄".

    签发它只需要一个持有者,名字从持有者推出来:

        self.id = ID(self)          # → name = "notedata"

    **只记名字,不持有那个对象**:`obj → id → obj` 会成环,块永远回收不掉.

    Attributes:
        name: 可读名称,由持有者推出;**表名取自它**.给持有者对象或给名字字符串都认.
        value_uuid: 分配形态凭证.**创建后只读**.
        birth_time: 该 ID 被签发的时刻(unix 纳秒).**创建后只读**;
            不等于块或数据的创建时间.
        in_hub: 所在 hub(目录名).**可写**:写入后由库记下.
        in_hub_pack: hub 内的载体.**可写**.
        in_pack_slot: 载体内的段列表(单格与区间两种形态).**可写**.
        body: **当前正文的摘要**(一个,不是一串);空串即这个块没有正文.
            **可写**;它是位置段之外的第二样库的事实.
    """

    __slots__ = (
        "_birth_time",
        "_name",
        "_value_uuid",
        "body",
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
        """签发一个 ID:名字从 `holder` 推出来,凭证与签发时刻当场定死.

        Args:
            holder: 持有者(`ID(self)`)或其名字(`ID("notedata")`).
            value_uuid: 分配形态凭证;不给即现签一个.**给它是为了由库里的行还原**.
            birth_time: 签发时刻(unix 纳秒);不给即取当前.**给它是为了由库里的行还原**.

        Raises:
            InvalidIdError: 分配形态凭证为空(空串是"没有身份",不是"待补").
        """
        self._name = _resolved_name(holder)
        self._value_uuid = value_uuid or new_uuid()
        if not self._value_uuid:
            raise InvalidIdError("分配形态凭证不能为空")
        self._birth_time = now_ns() if birth_time is None else int(birth_time)
        self.in_hub = ""
        self.in_hub_pack = ""
        self.in_pack_slot: list[SlotSpan] = []
        self.body: str = ""

    # ---- 锁死的三项 ---- #

    @property
    def name(self) -> str:
        """名字:由持有者推出,**之后不可改**(表名取自它)."""
        return self._name

    @property
    def value_uuid(self) -> str:
        """分配形态凭证:签发时定,**之后不可改**."""
        return self._value_uuid

    @property
    def birth_time(self) -> int:
        """该 ID 被签发的时刻:**之后不可改**."""
        return self._birth_time

    # ---- 问 ---- #

    @property
    def located(self) -> bool:
        """是否已写上物理坐标(hub,载体与段列表三样都有)."""
        return bool(self.in_hub) and bool(self.in_hub_pack) and bool(self.in_pack_slot)

    # ---- 位置段 ---- #

    def place(self, *spans: Iterable[SlotSpan], hub: str, pack: str) -> None:
        """把落盘后的坐标记到身份上:**这是位置段的唯一写入口**.

        可以一次给好几组:**组内相邻者并段,组与组之间不并**,次序照给的次序.
        分组的理由只有一条——**写侧的次序有语义**(属性槽在前,正文槽在后),
        而按格号归位会把这个次序翻过来,且**不报错**.

        **属性槽与正文槽不再另记一列**:哪一格是属性,哪一格是正文,载体上每一格的
        槽头本来就写着种类(`pack.ATTR_SLOT` / `pack.BODY_SLOT`),读侧按需读槽头分拣.

        Args:
            *spans: 一组或几组段(每组是若干单格或区间).
            hub: 落点所在的 hub.
            pack: 落点所在的载体名.
        """
        self.in_hub = hub
        self.in_hub_pack = pack
        self.in_pack_slot = _merge_groups(spans)

    def add_slot(self, slot: int) -> None:
        """把一个新写的格**接在位置段末尾**(相邻即并进最后那一段).

        **它给索引块用**:索引块一块接一块地收正表行,故它的位置段是"一格一格长出来"的.
        写一行的身份不是"它覆盖了谁"——把位置段整个换成新那几格,会把先前写的行丢掉,
        而**不报错**,只是查不到.
        """
        if self.in_pack_slot and isinstance(self.in_pack_slot[-1], tuple):
            first, last = self.in_pack_slot[-1]
            if last + 1 == slot:
                self.in_pack_slot[-1] = (first, slot)
                return
        if self.in_pack_slot and isinstance(self.in_pack_slot[-1], int):
            single = self.in_pack_slot[-1]
            if single + 1 == slot:
                self.in_pack_slot[-1] = (single, slot)
                return
        self.in_pack_slot.append(slot)

    def clear_place(self) -> None:
        """摘掉位置段与正文摘要(删除之后它们不该再指着已失效的坐标)."""
        self.in_hub = ""
        self.in_hub_pack = ""
        self.in_pack_slot = []
        self.body = ""

    @property
    def slots(self) -> tuple[int, ...]:
        """位置段覆盖的全部格号(展开成升序的一串),诊断与统计用.

        **它不说哪一格是属性,哪一格是正文**:那是槽头的事,不在这份坐标上.
        """
        found: list[int] = []
        for item in self.in_pack_slot:
            first, last = _bounds(item)
            found.extend(range(first, last + 1))
        return tuple(found)

    # ---- 库里的行 ---- #

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> ID:
        """由索引库那一行还原身份:**身份字段,位置段与正文摘要一起读回**.

        **写只写必需,读尽量读回**:分配形态必须有(它是这份身份的唯一性所在);
        名字与签发时刻允许缺失(那是"这一行没记");位置段与正文摘要各自解析,
        坏文本即抛,不静默吞掉脏值.

        Raises:
            InvalidIdError: 分配形态凭证缺失或为空,或整数字段 / 段列表形态非法.
        """
        try:
            value_uuid = str(row["value_uuid"] or "")
        except (KeyError, TypeError) as error:
            raise InvalidIdError(f"身份行缺少必需字段: {row!r}") from error
        if not value_uuid:
            raise InvalidIdError(f"身份行缺分配形态凭证: {row!r}")
        identity = cls(
            str(row.get("name") or ""),
            value_uuid=value_uuid,
            birth_time=_int_or_zero(row.get("birth_time")),
        )
        identity.in_hub = str(row.get("in_hub") or "")
        identity.in_hub_pack = str(row.get("in_hub_pack") or "")
        identity.in_pack_slot = list(parse_segments(str(row.get("in_pack_slot") or "")))
        identity.body = parse_body(str(row.get(BODY_FIELD) or ""))
        return identity

    def to_row(self) -> dict[str, object]:
        """折成库里那一行:**七列,一个不多**——`ID_FIELDS` 加正文摘要.

        位置段与正文摘要都是库的事实,而 `ID` 的字段里没有正文摘要——故那一列由身份
        自己带上,落点(hub,载体,段列表)与它同路.
        位置段按原次序写(不归位),故用的是 :func:`pack_segments_ordered`.
        """
        return {
            "name": self.name,
            "value_uuid": self.value_uuid,
            "birth_time": self.birth_time,
            "in_hub": self.in_hub,
            "in_hub_pack": self.in_hub_pack,
            "in_pack_slot": pack_segments_ordered(_slots_of_spans(self.in_pack_slot)),
            BODY_FIELD: self.body,
        }

    def __repr__(self) -> str:
        """诊断用:名字,凭证前一段,以及位置(若已落盘)."""
        where = "-"
        if self.located:
            where = f"{self.in_hub}/{self.in_hub_pack}[{pack_segments(self.in_pack_slot)}]"
        return f"ID(name={self.name!r}, uuid={self._value_uuid[:8]}…, at={where})"


ID_FIELDS: tuple[str, ...] = (
    "name",
    "value_uuid",
    "birth_time",
    "in_hub",
    "in_hub_pack",
    "in_pack_slot",
)
"""`ID` 的**身份与位置**字段名，顺序即声明顺序。

索引库里的列照这份清单逐列搬，**再加正文摘要那一列**（:data:`BODY_FIELD`），
故一张身份表恰好七列。清单是从 `ID` 上数出来的，不是另抄一份子集，故"某个字段进不去库"
在代码上不成立。**"哪几格是属性槽"不在这份清单里**：那是槽头的事，载体上写着。
"""


def _resolved_name(holder: object) -> str:
    """把持有者解析成名字:**`ID(self)` 是最省事的写法**.

    `self` 是持有者,也是写的人在 `__init__` 里唯一确定持有的东西;名字从它推出来,
    故不必在每个类里把类名再写一遍.传类(`ID(NoteData)`)得到同一个答案,两条路一致.
    传字符串即照用(由库里的行还原走这条).
    """
    if isinstance(holder, str):
        return holder
    resolved = getattr(holder, "__name__", None)
    if resolved is None:
        resolved = type(holder).__name__
    return str(resolved).lower()


def _int_or_zero(value: object) -> int:
    """把可选整数字段读回:缺失取 0,形态非法即抛(不静默吞掉脏值)."""
    if value is None:
        return 0
    try:
        return int(str(value))
    except ValueError as error:
        raise InvalidIdError(f"身份行的整数字段非法: {value!r}") from error


__all__ = [
    "BODY_FIELD",
    "EMPTY_SEGMENTS",
    "ID",
    "ID_FIELDS",
    "SlotSpan",
    "canonical_segments",
    "digest",
    "new_uuid",
    "pack_segments",
    "pack_segments_ordered",
    "parse_body",
    "parse_segments",
    "segments_of",
]
