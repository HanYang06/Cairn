# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""存储自己的一组配置（**存储的参数由存储声明，配置端只负责展开**）。

跑一次 ``uv run python tools/gen_conf.py`` 就会把它们展开成两份投影::

    config/settings/core/storage/conf.json    值（带默认值）
    schema/settings/core/storage/conf.json    词表（IDE 提示用）

（``settings`` 是默认 hub；换 hub 即换一组投影，见 `core.conf.engine`。）

取用::

    from core.storage.conf import conf

    slot = conf.pack_slot_bytes

**什么该进这里、什么不该**（判据是"谁有权改它"）：

- **配置键** —— 人能调、调了不坏库的东西：分片粒度、封口线、槽长；
- **格式常量** —— 改了就坏库或换格式的东西：载体魔数、文件头长度、记录头布局。
  它们留在实现处（`core/storage/carrier.py`），**不进配置**：
  配置里出现一个代码不读的键，比没有这个键更坏。

槽长的取值由实验确定（设计篇 §5.6 标为待定），故此处只给可改的初值。
"""

from __future__ import annotations

from typing import Any

from core.types.cfg import Cfg

from ._defaults import DEFAULT_TABLES, TABLE_SHAPE


class StorageConf:
    """存储参数（分片粒度 / 载体封口 / 槽长 / **表声明**）。"""

    block_max_bytes: Cfg = Cfg(
        "storage.block.max_bytes",
        1024 * 1024,
        doc="单个块的字节上限，超过即分片（分片 + 索引块）",
    )
    pack_max_bytes: Cfg = Cfg(
        "storage.pack.max_bytes",
        2 * 1024 * 1024 * 1024,
        doc="单个载体的字节上限，写满即封口（只管封口线，不定槽长）",
    )
    pack_slot_bytes: Cfg = Cfg(
        "storage.pack.slot_bytes",
        64 * 1024,
        doc="槽长：载体内的定长分配与定位单位，建载体时写进文件头",
    )
    db_tables: Cfg = Cfg(
        "storage.db.tables",
        DEFAULT_TABLES,
        item_type=list[dict[str, Any]],
        structure=TABLE_SHAPE,
        doc="索引库的表声明（**本体在这**：改它即改表；列项顺序即建表顺序）",
    )


conf = StorageConf()
"""存储配置入口。"""


__all__ = ["StorageConf", "conf"]
