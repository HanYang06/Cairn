<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 配置项参考

!!! danger "本页由工具生成，请勿手改"

    由 `uv run python scripts/docgen.py --write` 生成，表来自 **配置声明现算**（`core/conf` 的
    词表投影，副本落在 `config/schema/settings.json`）。改口径请改生成器，改配置请改声明的
    那个 `conf(...)` 调用点；`--check` 已进 CI，漂移即失败。**手改这一页会在下一次生成时被抹掉。**

## 怎么读这张表

- **键** = 点分路径，也是 `config/settings.json` 里的属性名（不展开成嵌套对象）。
- **默认值** = 声明里给的默认；`—` 表示没有默认值（那种键的值必须由文件给，丢了即报错）。
- **取值** = `conf("键")`；**声明** = `conf("键", 默认值, type=…, doc=…)`——同一个调用形，
  差别只在给不给参数。写入方向是单向的：改值改 `config/settings.json`，除非显式 `force=True`。

## 全部配置项（9 条）

| 键 | 类型 | 默认值 | 说明 | 声明处 |
|---|---|---|---|---|
| `core.log.level` | `string` | `WARNING` | 内核日志级别：导入内核时设到 core.* 这族记录器 | `py_src/core/conf/params.py:16` |
| `hub.default` | `string` | `main` | 默认 hub 名：写入不点名时进这一个 | `py_src/core/storage/conf.py:87` |
| `index.max.byte` | `integer` | `67108864` | 一个索引块的体积上限（字节）：写到这个数由引擎自动续下一块 | `py_src/core/storage/conf.py:88` |
| `pack.max.byte` | `integer` | `2147483648` | 封口线（字节）：单个载体写满这个数就换新的一份；只管换文件，不是硬上限 | `py_src/core/storage/conf.py:81` |
| `slot.max.byte.b` | `integer` | `512` | 格长档位之一：每单位 1 字节；五档相加即为格长，全不写则不成立 | `py_src/core/storage/conf.py:62` |
| `slot.max.byte.gb` | `integer` | `0` | 格长档位之一：每单位 1073741824 字节；五档相加即为格长，全不写则不成立 | `py_src/core/storage/conf.py:62` |
| `slot.max.byte.kb` | `integer` | `0` | 格长档位之一：每单位 1024 字节；五档相加即为格长，全不写则不成立 | `py_src/core/storage/conf.py:62` |
| `slot.max.byte.mb` | `integer` | `0` | 格长档位之一：每单位 1048576 字节；五档相加即为格长，全不写则不成立 | `py_src/core/storage/conf.py:62` |
| `slot.max.byte.tb` | `integer` | `0` | 格长档位之一：每单位 1099511627776 字节；五档相加即为格长，全不写则不成立 | `py_src/core/storage/conf.py:62` |

## 另见

- 用法契约与形状由来：[配置引擎](../architecture/py_core/config.md)
- 值文件 `config/settings.json`、词表 `config/schema/settings.json`——**跑一遍程序就生成**
  （引擎退出时落盘，不需要专门的生成脚本）。
- 格式常量（载体魔数、文件头长度、记录头布局这类改了会坏库的）**故意不进配置**，留在实现处。
- 想加一条配置：在**用到它的那个包**里声明（例：`py_src/core/storage/conf.py`），
  再跑一次 `uv run python scripts/docgen.py --write` 把这一页更新。
