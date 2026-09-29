<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 配置项参考

!!! danger "本页由工具生成，请勿手改"

    由 `uv run python tools/docgen.py --write` 生成，表来自 **配置声明现算**（`core/conf` 的
    词表投影，副本落在 `config/schema/settings.json`）。改口径请改生成器，改配置请改声明的
    那个 `conf(...)` 调用点；`--check` 已进 CI，漂移即失败。**手改这一页会在下一次生成时被抹掉。**

## 怎么读这张表

- **键** = 点分路径，也是 `config/settings.json` 里的属性名（不展开成嵌套对象）。
- **默认值** = 声明里给的默认；`—` 表示没有默认值（那种键的值必须由文件给，丢了即报错）。
- **取值** = `conf("键")`；**声明** = `conf("键", 默认值, type=…, doc=…)`——同一个调用形，
  差别只在给不给参数。写入方向是单向的：改值改 `config/settings.json`，除非显式 `force=True`。

## 全部配置项（5 条）

| 键 | 类型 | 默认值 | 说明 | 声明处 |
|---|---|---|---|---|
| `core.log.level` | `string` | `WARNING` | 内核日志级别：导入内核时设到 core.* 这族记录器 | `src/core/conf/params.py:16` |
| `storage.block.max_bytes` | `integer` | `1048576` | 单个块的字节上限，超过即分片（预留，尚未接线） | `src/core/storage/conf.py:43` |
| `storage.db.tables` | `string` | `tables.yaml` | 索引库表声明所在文件（结构本体在那） | `src/core/storage/conf.py:44` |
| `storage.pack.max_bytes` | `integer` | `2147483648` | 单个载体的字节上限，写满即封口（只管封口线，不定槽长） | `src/core/storage/conf.py:37` |
| `storage.pack.slot_bytes` | `integer` | `512` | 槽长：载体内的定长分配与定位单位，写进文件头 | `src/core/storage/conf.py:36` |

## 另见

- 用法契约与形状由来：[配置引擎](../architecture/config.md)
- 值文件 `config/settings.json`、词表 `config/schema/settings.json`——**跑一遍程序就生成**
  （引擎退出时落盘，不需要专门的生成脚本）。
- 格式常量（载体魔数、文件头长度、记录头布局这类改了会坏库的）**故意不进配置**，留在实现处。
- 想加一条配置：在**用到它的那个包**里声明（例：`src/core/storage/conf.py`），
  再跑一次 `uv run python tools/docgen.py --write` 把这一页更新。
