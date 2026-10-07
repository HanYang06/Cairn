# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""存储这一层的配置声明:格长,封口线,默认 hub,索引块上限,自动回收阈值.

**各管各的**:本包要用配置,就在本包声明——内核自身那几条在 `core/params.py`.
声明即事实:默认值只写这一份,值文件由引擎(OnConf)展开;改值改 `config/settings.json`,
改默认值改这里.

五组键,各自回答一个问题:

| 键 | 回答什么 | 取它用 |
|---|---|---|
| `slot.max.byte.{b,kb}` | 新建载体的格长 | :func:`slot_bytes` |
| `pack.max.byte` | 一个载体写到多大换新的一份 | :func:`pack_max_bytes` |
| `hub.default` | 不点名时写进哪个 hub | :func:`default_hub_name` |
| `index.max.byte` | 一个索引块写到多大续下一块 | :func:`index_max_bytes` |
| `gc.auto.byte` | 死字节到多少自动回收(`0` 即不自动) | :func:`gc_auto_bytes` |

**格长按两档相加**:任何一档不写都成立(那档算零),**两档全不写则不成立**——那等于格长为零,
当场报错.相加是为了用整数精确表示:只给一个"带小数的兆"就得碰浮点,而格长是**格式事实**,
浮点误差会直接错位到偏移算术里.**兆 / 吉 / 太三档按 2026-10-02 裁定清掉**:格长是格内浪费的
上界,兆以上的档没有用处.

**其余三条是策略,不是格式事实**:`pack.max.byte` / `index.max.byte` / `gc.auto.byte`
只决定"什么时候换文件 / 续块 / 回收",改大改小都不会让已落盘的字节错位——
格长随载体走(写在文件头里),故它们读的是当前值,不缓存.

格式常量(载体魔数,文件头长度,槽头布局这类改了会坏库的)**故意不进配置**,留在实现处.
"""

from __future__ import annotations

from onconf import conf

from core.exc import SlotSizeError

from .hub import DEFAULT_SLOT_BYTES
from .pack import DEFAULT_MAX_BYTES

SLOT_MAX_BYTE = "slot.max.byte.b"
"""格长档位：字节。**开箱的一档**：默认 512 B，另一档留空。"""

SLOT_MAX_KBYTE = "slot.max.byte.kb"
"""格长档位：千字节（1024 进制）。"""

_TIERS: tuple[tuple[str, int], ...] = (
    (SLOT_MAX_BYTE, 1),
    (SLOT_MAX_KBYTE, 1024),
)
"""两档与各自的倍数，**顺序即书写的顺序**（相加与报告都按它走）。"""

for _path, _factor in _TIERS:
    conf(
        _path,
        DEFAULT_SLOT_BYTES if _path == SLOT_MAX_BYTE else 0,
        doc=f"格长档位之一：每单位 {_factor} 字节；两档相加即为格长，全不写则不成立",
    )

PACK_MAX_BYTE = "pack.max.byte"
"""封口线（字节）：单个载体写满这个数就换新的一份。**只管换不换文件**，不是单条记录的硬上限。"""

HUB_DEFAULT = "hub.default"
"""默认 hub 名：写入时不点名就进这一个。"""

INDEX_MAX_BYTE = "index.max.byte"
"""一个索引块的体积上限（字节）：写完一块到这个数，引擎自动开下一块。

索引块是块，块有体积上限：改它即改"隔多久续一块"。块自己可以用 `Block.max_bytes` 覆盖它。
"""

GC_AUTO_BYTE = "gc.auto.byte"
"""自动回收的阈值（字节）：死字节到这个数即自动回收；`0` 即不自动回收。"""

conf(
    PACK_MAX_BYTE,
    DEFAULT_MAX_BYTES,
    doc="封口线（字节）：单个载体写满这个数就换新的一份；只管换文件，不是硬上限",
)
conf(HUB_DEFAULT, "main", doc="默认 hub 名：写入不点名时进这一个")
conf(
    INDEX_MAX_BYTE,
    64 * 1024**2,
    doc="一个索引块的体积上限（字节）：写到这个数由引擎自动续下一块",
)
conf(
    GC_AUTO_BYTE,
    0,
    doc="自动回收的阈值（字节）：死字节到这个数即自动回收；0 即不自动回收",
)


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
    return int(conf(PACK_MAX_BYTE))


def default_hub_name() -> str:
    """当前默认 hub 名."""
    return str(conf(HUB_DEFAULT))


def index_max_bytes() -> int:
    """当前索引块上限(字节)."""
    return int(conf(INDEX_MAX_BYTE))


def gc_auto_bytes() -> int:
    """当前自动回收的阈值(字节);`0` 即不自动回收."""
    return int(conf(GC_AUTO_BYTE))


__all__ = [
    "DEFAULT_SLOT_BYTES",
    "GC_AUTO_BYTE",
    "HUB_DEFAULT",
    "INDEX_MAX_BYTE",
    "PACK_MAX_BYTE",
    "SLOT_MAX_BYTE",
    "SLOT_MAX_KBYTE",
    "default_hub_name",
    "gc_auto_bytes",
    "index_max_bytes",
    "pack_max_bytes",
    "slot_bytes",
]
