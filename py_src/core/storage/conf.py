# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""存储那组配置声明。

**各管各的**：存储的参数由存储自己声明，配置端只负责展开与取值，不替别人管。
内核那个模块（`core/conf/params.py`）声明的是日志级别一类，与这里互不干涉。

三条规矩（与设计篇 §5.5 同口径）：

- **格式常量不进配置**：载体魔数、文件头长度、记录头布局这类改了会坏库的，留在实现处；
- **已落盘的东西不被新配置改写**：槽长在建载体时写进文件头，此后一律按文件头读——
  改配置不会让老载体的偏移错位；
- **取用点不抄默认值**：要值就向引擎要（`conf("storage.pack.slot_bytes")`），
  默认值只写在下面这几行里。
"""

from __future__ import annotations

from core.conf import conf
from core.storage.hub import DEFAULT_MAX_BYTES, DEFAULT_SLOT_BYTES

SLOT_BYTES = "storage.pack.slot_bytes"
"""键名常量：取用点写常量而不是各处抄字符串，改名只改这一处。"""

PACK_MAX_BYTES = "storage.pack.max_bytes"
"""键名常量：载体封口线。"""

BLOCK_MAX_BYTES = "storage.block.max_bytes"
"""键名常量：块的分片粒度（**预留**：分片尚未接进块面）。"""

# 声明处的默认值直接引用实现里的那两个常量：一份事实、两处引用，比在这里抄一个数字好。
conf(SLOT_BYTES, DEFAULT_SLOT_BYTES, type=int, doc="槽长：载体内的定长分配与定位单位，写进文件头")
conf(
    PACK_MAX_BYTES,
    DEFAULT_MAX_BYTES,
    type=int,
    doc="单个载体的字节上限，写满即封口（只管封口线，不定槽长）",
)
conf(BLOCK_MAX_BYTES, 1024**2, type=int, doc="单个块的字节上限，超过即分片（预留，尚未接线）")

__all__ = ["BLOCK_MAX_BYTES", "PACK_MAX_BYTES", "SLOT_BYTES"]
