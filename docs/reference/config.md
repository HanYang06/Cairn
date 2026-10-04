<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 配置项参考

!!! danger "本页由工具生成，请勿手改"

    由 `uv run python scripts/docgen.py --write` 生成：键 / 类型 / 默认值 / 说明来自
    **入库的词表**（`config/schema/settings.json`，由 OnConf 从声明现算），「声明处」由
    **AST 扫 `conf(...)` 调用点**得出。改口径请改生成器，改配置请改声明的那个 `conf(...)`
    调用点；`--check` 已进 CI，漂移即失败。**手改这一页会在下一次生成时被抹掉。**

## 怎么读这张表

- **键** = 点分路径，也是 `config/settings.json` 里的属性名（不展开成嵌套对象）。
- **默认值** = 声明里给的默认；`—` 表示没有默认值（那种键的值必须由文件给，丢了即报错）。
- **取值** = `conf("键")`；**声明** = `conf("键", 默认值, type=…, doc=…)`——同一个调用形，
  差别只在给不给参数。写入方向是单向的：改值改 `config/settings.json`，除非显式 `force=True`。
- **声明处**为 `—` 的键写在一个循环或函数里（键不是字面量），AST 扫不出逐键的出处；
  那种写法的键与说明仍以词表为准。

## 全部配置项（8 条）

| 键 | 类型 | 默认值 | 说明 | 声明处 |
|---|---|---|---|---|
| `body.history.depth` | `integer` | `1` | 正文保留的世代数：改一段正文即新建一个槽，超出这个数的最老世代可被回收 | `—` |
| `core.log.level` | `string` | `WARNING` | 内核日志级别：导入内核时设到 cairn 这族记录器 | `core/params.py:16` |
| `gc.auto.byte` | `integer` | `0` | 自动回收的阈值（字节）：死字节到这个数即自动回收；0 即不自动回收 | `—` |
| `hub.default` | `string` | `main` | 默认 hub 名：写入不点名时进这一个 | `—` |
| `index.max.byte` | `integer` | `67108864` | 一个索引块的体积上限（字节）：写到这个数由引擎自动续下一块 | `—` |
| `pack.max.byte` | `integer` | `2147483648` | 封口线（字节）：单个载体写满这个数就换新的一份；只管换文件，不是硬上限 | `—` |
| `slot.max.byte.b` | `integer` | `512` | 格长档位之一：每单位 1 字节；两档相加即为格长，全不写则不成立 | `—` |
| `slot.max.byte.kb` | `integer` | `0` | 格长档位之一：每单位 1024 字节；两档相加即为格长，全不写则不成立 | `—` |

## 另见

- 用法契约与形状由来：[配置引擎](../architecture/py_core/config.md)
- 值文件 `config/settings.json`、词表 `config/schema/settings.json`——**跑一遍程序就生成**
  （OnConf 在提交点落盘，不需要专门的生成脚本）。
- 格式常量（载体魔数、文件头长度、槽头布局这类改了会坏库的）**故意不进配置**，留在实现处。
- 想加一条配置：在**用到它的那个包**里声明（例：`py_src/core/storage/conf.py`），
  再跑一次 `uv run python scripts/docgen.py --write` 把这一页更新。
