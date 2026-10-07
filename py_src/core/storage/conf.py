# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""存储这一层的配置声明:格长,封口线,默认 hub,索引块上限,自动回收阈值.

**各管各的**:本包要用配置,就在本包声明——内核自身那几条在 `core/params.py`.
声明即事实:默认值只写这一份,值文件由引擎(OnConf)展开;改值改 `config/settings.json`,
改默认值改这里.

**键名按 `<层>.<域>.<对象>.<属性>` 写**:本层五条一律带 `core.storage.` 前缀,与声明所在的
包(`core/storage/`)对得上.

**声明处必须是字面量**:OnConf 的静态面(`onconf build` / `sync` / `check`)靠 AST 认"调用点上的
字面量"——键与默认值都要能 `ast.literal_eval` 求出来,写成常量名或算式就进不了它的期望集,
于是 `check` 把已入库的键报成"没声明",`build` 又照不完整的期望集重写值文件.故这里把键与
默认值写死;取值那一侧照旧写同一个字面量(读不进静态面,常量与字面量在那儿等价).

五组键,各自回答一个问题:

| 键 | 回答什么 | 取它用 |
|---|---|---|
| `core.storage.slot.max.byte.{b,kb}` | 新建载体的格长 | :func:`slot_bytes` |
| `core.storage.pack.max.byte` | 一个载体写到多大换新的一份 | :func:`pack_max_bytes` |
| `core.storage.hub.default` | 不点名时写进哪个 hub | :func:`default_hub_name` |
| `core.storage.index.max.byte` | 一个索引块写到多大续下一块 | :func:`index_max_bytes` |
| `core.storage.gc.auto.byte` | 死字节到多少自动回收(`0` 即不自动) | :func:`gc_auto_bytes` |

**格长按两档相加**:任何一档不写都成立(那档算零),**两档全不写则不成立**——那等于格长为零,
当场报错.相加是为了用整数精确表示:只给一个"带小数的兆"就得碰浮点,而格长是**格式事实**,
浮点误差会直接错位到偏移算术里.**兆 / 吉 / 太三档按 2026-10-02 裁定清掉**:格长是格内浪费的
上界,兆以上的档没有用处.

**其余三条是策略,不是格式事实**:`core.storage.pack.max.byte` / `core.storage.index.max.byte` /
`core.storage.gc.auto.byte` 只决定"什么时候换文件 / 续块 / 回收",改大改小都不会让已落盘的字节
错位——格长随载体走(写在文件头里),故它们读的是当前值,不缓存.

格式常量(载体魔数,文件头长度,槽头布局这类改了会坏库的)**故意不进配置**,留在实现处.
"""

from __future__ import annotations

from onconf import conf

from core.exc import SlotSizeError

conf(
    "core.storage.slot.max.byte.b",
    512,
    doc="格长档位之一：每单位 1 字节；两档相加即为格长，全不写则不成立",
)
conf(
    "core.storage.slot.max.byte.kb",
    0,
    doc="格长档位之一：每单位 1024 字节；两档相加即为格长，全不写则不成立",
)
conf(
    "core.storage.pack.max.byte",
    2_147_483_648,
    doc="封口线（字节）：单个载体写满这个数就换新的一份；只管换文件，不是硬上限",
)
conf("core.storage.hub.default", "main", doc="默认 hub 名：写入不点名时进这一个")
conf(
    "core.storage.index.max.byte",
    67_108_864,
    doc="一个索引块的体积上限（字节）：写到这个数由引擎自动续下一块",
)
conf(
    "core.storage.gc.auto.byte",
    0,
    doc="自动回收的阈值（字节）：死字节到这个数即自动回收；0 即不自动回收",
)

_TIERS: tuple[tuple[str, int], ...] = (
    ("core.storage.slot.max.byte.b", 1),
    ("core.storage.slot.max.byte.kb", 1024),
)
"""两档与各自的倍数,**顺序即书写的顺序**(相加与报告都按它走);只给读侧的求和用."""


def slot_bytes() -> int:
    """当前格长:两档相加归一成字节数.

    它只决定**新建载体时写进文件头的那个数**;读取已有载体一律从文件头读格长,
    改配置不会让已落盘的载体错位.

    Returns:
        格长(字节).

    Raises:
        SlotSizeError: 两档全为空(格长为零),或哪一档写了负数.
    """
    total = 0
    for path, factor in _TIERS:
        value = int(conf(path))
        if value < 0:
            raise SlotSizeError(f"格长档位 {path!r} 不能为负: {value}")
        total += value * factor
    if total <= 0:
        raise SlotSizeError(
            "格长没有来源："
            f"{'、'.join(path for path, _ in _TIERS)} 至少要写一档"
            "（两档相加即为格长；全不写等于零）"
        )
    return total


def pack_max_bytes() -> int:
    """当前封口线(字节):单个载体写满它就换新的一份."""
    return int(conf("core.storage.pack.max.byte"))


def default_hub_name() -> str:
    """当前默认 hub 名."""
    return str(conf("core.storage.hub.default"))


def index_max_bytes() -> int:
    """当前索引块上限(字节)."""
    return int(conf("core.storage.index.max.byte"))


def gc_auto_bytes() -> int:
    """当前自动回收的阈值(字节);`0` 即不自动回收."""
    return int(conf("core.storage.gc.auto.byte"))


__all__ = [
    "default_hub_name",
    "gc_auto_bytes",
    "index_max_bytes",
    "pack_max_bytes",
    "slot_bytes",
]
