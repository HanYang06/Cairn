<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 配置项参考

!!! danger "本页由工具生成，请勿手改"

    由 `uv run python scripts/docgen.py --write` 生成：键 / 默认值 / 说明来自
    **入库的词表**（`config/schema/settings.json`，由 OnConf 从声明现算），「声明处」由
    **AST 扫 `conf(...)` 调用点**得出。改口径请改生成器，改配置请改声明的那个 `conf(...)`
    调用点；`--check` 已进 CI，漂移即失败。**手改这一页会在下一次生成时被抹掉。**

## 怎么读这张表

- **键** = 点分路径，也是 `config/settings.json` 里的属性名（不展开成嵌套对象）。
- **默认值** = 声明里给的默认；`—` 表示没有默认值（那种键的值必须由文件给，丢了即报错）。
- **取值** = `conf("键")`；**声明** = `conf("键", 默认值, doc=…)`——同一个调用形，
  差别只在给不给参数。写入方向是单向的：改值改 `config/settings.json`；
  运行期没有覆盖出口，覆盖走命令行 `onconf build` / `sync`。
- **声明处**由 AST 扫 `conf(...)` 的**字面量键**得出；键写成常量名或写在循环里就扫不出逐键的
  出处，那一格显示 `—`——OnConf 的静态面同样认不出，`onconf check --strict` 会当场失败。

## 全部配置项（7 条）

| 键 | 默认值 | 说明 | 声明处 |
|---|---|---|---|
| `core.log.level` | `WARNING` | 内核日志级别：导入内核时设到 cairn 这族记录器 | `core/params.py:18` |
| `core.storage.gc.auto.byte` | `0` | 自动回收的阈值（字节）：死字节到这个数即自动回收；0 即不自动回收 | `core/storage/conf.py:66` |
| `core.storage.hub.default` | `main` | 默认 hub 名：写入不点名时进这一个 | `core/storage/conf.py:60` |
| `core.storage.index.max.byte` | `67108864` | 一个索引块的体积上限（字节）：写到这个数由引擎自动续下一块 | `core/storage/conf.py:61` |
| `core.storage.pack.max.byte` | `2147483648` | 封口线（字节）：单个载体写满这个数就换新的一份；只管换文件，不是硬上限 | `core/storage/conf.py:55` |
| `core.storage.slot.max.byte.b` | `512` | 格长档位之一：每单位 1 字节；两档相加即为格长，全不写则不成立 | `core/storage/conf.py:45` |
| `core.storage.slot.max.byte.kb` | `0` | 格长档位之一：每单位 1024 字节；两档相加即为格长，全不写则不成立 | `core/storage/conf.py:50` |

## 另见

- 用法契约与形状由来：[配置引擎](../architecture/py_core/config.md)
- 值文件 `config/settings.json`、词表 `config/schema/settings.json`——**跑一遍程序就生成**
  （OnConf 在提交点落盘，不需要专门的生成脚本）。
- 格式常量（载体魔数、文件头长度、槽头布局这类改了会坏库的）**故意不进配置**，留在实现处。
- 想加一条配置：在**用到它的那个包**里声明（例：`py_src/core/storage/conf.py`），键名按
  `<层>.<域>.<对象>.<属性>` 取（层前缀与所在的包一致）、键与默认值写成**字面量**，
  再跑一次 `uv run python scripts/docgen.py --write` 把这一页更新。
