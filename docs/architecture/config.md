<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 配置（Config）

> 状态：**草案 v0.1**（2026-09-26 落地第一片；引擎 + 声明 + 两个投影）。
> 事实源：`src/core/conf/`（引擎）与 `src/core/types/cfg.py`（声明类型）；本文件是**用法契约**。

## 1. 一句话

**声明即事实，两个投影落在磁盘上**：一组配置在声明模块里用 `Cfg` 定"是什么、默认多少"，
引擎把它展开成 **值**（`config/`）与 **词表**（`schema/`）两份文件；取用时文件说了算、缺了用默认值、
默认值也没有就报错。

## 2. 两套目录一一对应

```
config/<hub>/<包树>/<文件>.json   ← 值（软配置；带默认值的项在这里呈现）
schema/<hub>/<包树>/<文件>.json   ← 词表（永远 json；给 IDE 与分发包看）
schema/<hub>.json                 ← 总词表（所有声明的入口，含 $id）
```

`<hub>` 是**命名空间**（默认 `settings`）：换一个 hub 就换一组投影——生成物与手写口各用一个 hub，
于是"生成物把别人的文件覆盖掉"从结构上就不会发生，再加一道**重名检查**兜底（见 §5.1）。

`<包树>` 与 `src/<包树>` 同构：

| 声明写在哪 | 值 | 词表 |
|---|---|---|
| `src/core/storage/conf.py` | `config/settings/core/storage/conf.json` | `schema/settings/core/storage/conf.json` |
| `src/core/conf/params.py` | `config/settings/core/conf/params.json` | `schema/settings/core/conf/params.json` |

**哪个文件声明，就落哪份同名配置**——不另立映射表。

### 2.1 两份词表的严格度不同（有意）

- **分片词表**（`schema/<hub>/<包树>/<文件>.json`）：值文件顶部的 `$schema` 指向它，**不禁未登记键**
  （`additionalProperties` 不设 `false`）。理由：引擎的投影策略是「只补缺失的键、不删不改」，
  用户自己加的键会被保留下来；分片若宣布它们非法，IDE 会把合法文件标成错的。
  代价是**拼错的键也不会被分片挡下**（如 `core.log.levle`）。
- **总词表**（`schema/<hub>.json`）：列全部声明的键，且 `additionalProperties: false`——
  它是"有没有这个键"的权威入口（分发包与总览用）。

要严格校验一份值文件的键名，用总词表对；分片只负责给悬停提示。

## 3. 怎么声明（各管各的）

一组配置 = 声明方包里的一个模块（建议 `conf.py`；**`core/conf` 自己那个必须叫 `params.py`**，
否则包名与同名子模块互相覆盖）：

```python
# src/core/storage/conf.py
from core.types.cfg import Cfg


class StorageConf:
    """存储参数。"""

    pack_max_blocks: Cfg = Cfg("storage.pack.max_blocks", 4096, doc="单个载体最多装多少块")


conf = StorageConf()
```

取用方：

```python
from core.storage.conf import conf

blocks = conf.pack_max_blocks  # 读属性 = 向引擎要值
```

`Cfg(path, default, *, doc, empty_ok, item_type)`：

| 参数 | 含义 |
|---|---|
| `path` | 点分键（`storage.pack.max_blocks`）；也是分组依据 |
| `default` | **带了值 → 这条会展开进 `config/`**；不带 → 只进词表，值丢了报错。**不得传空值**（`None` / 空串 / 空容器都会写出读不回来的默认值，声明期即拒绝）——确需以空为默认时配 `empty_ok=True` |
| `doc` | 写进词表的说明（IDE 悬停能看到） |
| `empty_ok` | `empty_ok=True` 那套增强写法：空值（`""` / `None` / `[]`）也按默认处理 |
| `item_type` | 显式类型；不写就取注解 `Cfg[int]`，注解没信息再按默认值推。联合与泛型（`int \| None`、`list[int]`）同样采纳 |

## 4. 取值三条（引擎的判据）

| 文件里的状态 | 有默认值？ | 行为 |
|---|---|---|
| key 在、值空 | 任意 | **报错**（`ConfigValueError`）——不猜、不自动修 |
| key 丢了 | 有 | **补回默认值**（文件删了也能重展开） |
| key 丢了 | 没有 | **报错**（`ConfigKeyError`）——补不了 |

- **用户改过的值永不被覆写**：补只补"缺失的键"；
- `conf.get(key)` / `conf.set(key, value)`：写只走 `set`（写进值文件）；`conf.reload()` 丢缓存。

## 5. 生成投影（工程工具）

```powershell
uv run python tools/gen_conf.py            # 展开 / 补齐
uv run python tools/gen_conf.py --check    # 只查不写（CI 防漂移）
```

新增一组配置后：在 `tools/gen_conf.py` 顶部的 import 清单里**补一行**（导入即登记）。

### 5.1 重名检查（不覆盖别人的文件）

目标路径上已经存在、且**认不出是本引擎的投影**时，引擎**拒写**并按情形抛错：

| 情形 | 判据 | 结果 |
|---|---|---|
| 别人的文件 | 有 `$schema` 但**指向别处** | `ConfigConflictError`（拒写） |
| 无标记的文件 | 没有 `$schema`，也找不到本引擎为它登记过的键 | `ConfigConflictError`（拒写） |
| 空文件 | 根是**空对象**（`{}`） | 不算冲突：没有他人内容可覆盖，键丢了照旧补回来 |
| 坏文件 | 读不成 JSON / 根不是对象 | `ConfigFileError` |

判据只有一处（`ConfEngine._clash`），**所有写入口共用**：批量落盘（`sync`）、单值写（`set`，
即 `conf.xxx = …`）、补缺失键（`get` 触发的 `_repair`）都守同一道口——
"绝不覆盖别人的文件"不是只有批量写才守。

写值文件还会**规范化键序**（在册键按声明顺序在前、用户键在后）并与 `plan()` 共用同一处排序：
`--check` 按文本逐字节比较，两处若各排一种序，等价内容会被误报成漂移。

`tools/gen_conf.py` 会先把冲突逐条列出来让人处理——**搬迁或换 hub**，绝不静默覆盖。

## 6. 已经接上的线

声明不只是"记着"，它**真的驱动行为**：

| 配置项 | 谁读它 | 怎么生效 |
|---|---|---|
| `storage.pack.slot_bytes` | `CarrierFile.create` | 建载体时写进文件头（**此后按文件头读**，不再问配置） |
| `storage.pack.max_bytes` | `Bucket.pack_max_bytes` | 封口线：写满即换新载体（每次写入按当前值判） |
| `storage.block.max_bytes` | —— | 分片粒度（**预留**：分片尚未接进块面，见存储设计篇 §12） |
| `storage.db.tables` | `core/storage/tables.py` | **文件引用**：值是相对引用名，本体是那份 YAML 表声明 |
| `core.log.level` | `core/__init__` | 导入内核即设 `core.*` 这族 logger 的级别（不劫持 root） |

两条使用规矩：

- 值的默认值**来自声明**（`core/storage/conf.py`），这里不抄第二份；
  **已落盘的东西不被新配置改写**（槽长写在载体文件头里，老库不会因改配置而被解释成另一个布局）；
- 改配置文件即改行为：策略类参数（如封口线）每次取用都向引擎要值。

## 7. 边界（别越界）

- **各模块管自己的配置**：`core/storage` 的参数由 `core/storage` 声明，配置端只负责展开，
  不替别人管；
- **格式常量不进配置**：载体魔数、文件头长度、记录头布局这类改了会坏库的，留在实现处；
- **引擎不依赖第三方**：`core/conf` 只用标准库 + `core.types`；`jsonschema` 只在测试 / 可选校验里用；
- **配置不是"统一参数面"**：它只管配置这件事；UI 侧 `ui_tools` 的 Facet 配置是另一套，两者不合并。

## 8. 未做（如实记）

- 手写口（个人覆写 / 多 hub 读取合并）：hub 机制已在，第二个 hub 尚未启用；
- `jsonschema` 校验路径（现在词表只给人看，运行期不做 schema 校验）；
- 环境旋钮（`CAIRN_VAULT` / `CAIRN_THEME_DIR` / `CAIRN_SHAPES`）**暂不进配置**：
  它们是开发 / 部署时的入口，且测试靠 monkeypatch env 重定向；要收进来再定优先级；
- 引擎与内核门户（`Core` 表一）的接线：`Conf` 实例尚未挂载；
- 声明消失时值文件里旧键的清理（现在**只保留不动**，用户改过的不该被引擎删）。
