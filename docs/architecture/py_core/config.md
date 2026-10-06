<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 配置引擎

> 状态：**现行**（2026-10-04 换成 OnConf）。
> 事实源：`py_src/core/conf.py`（**外层**：定配置根 + 转发 `conf`）、各包自己的声明模块
> （`core/params.py`、`core/storage/conf.py`）、以及**上游库** OnConf
> （PyPI 名 `onconf`，Apache-2.0）。本文件是**用法契约**；引擎自身的语义以上游文档为准，
> 此处只记"内核侧怎么接的、与旧引擎差在哪、边界在哪"。

## 1. 一句话

**内核不再自带配置引擎**。`core/conf.py` 只做两件事：**定配置根**（`CAIRN_CONFIG` 指的目录，
不给就用仓根下的 `config/`），然后**把 OnConf 的 `conf` 原样交出去**。调用形与换成内建引擎
之前逐字一致：

```python
from core.conf import conf

conf("pack.max.byte", 2 * 1024**3, type=int, doc="封口线")  # 声明
ceiling = conf("pack.max.byte")  # 取值
```

**使用点统一**：import 之后任何位置都可直接调用。全仓只扫 `conf(` 这一个词即可列出全部使用点。

**为什么要多这一层**：OnConf 的引擎是**单例**，且"起来之后不能就地改配置"——配置根必须在
**第一次 `conf()` 之前**定下来。内核的声明模块正是在导入期调 `conf()` 的，故由这一层在导入时
先把引擎指好，消除"谁先调用谁定根"的顺序依赖。

## 2. 声明与取值：同一种调用

| 写法 | 含义 |
|---|---|
| `conf("a.b", 默认值, type=…, doc=…)` | **声明**（文件里没有就补上） |
| `conf("a.b", type=…, doc=…)` | 登记一个**没有默认值**的项 ⇒ 紧接着取值，没配即报错 |
| `conf("a.b")` | **取值** |

参数：`key`（点分键）／`value`（默认值，不给即取值的判据）／`type`（声明期类型校验）／
`doc`（写进词表，IDE 悬停可见）／`force`（强写，见 §4）。

- **声明是唯一事实来源**：默认值只写在声明处，实现里不抄第二份（存储那组直接引用
  `pack.DEFAULT_MAX_BYTES` 与 `hub.DEFAULT_SLOT_BYTES`，一份事实、两处引用）；
- **键逐字保留点分形式**，值文件里 `"pack.max.byte"` 就是一个属性名，不展开成嵌套对象。

## 3. 落盘：默认即时，进程退出兜底

| 通路 | 做什么 | 使用方 |
|---|---|---|
| **默认** | 每次 `conf(k, v)` 当场提交（OnConf 的 `flush_window=0`） | 日常写法 |
| **`core.conf.sync()`** | 显式完整提交（含"清理未知键"） | 工具、测试、要求"文件此刻是对的" |
| **`force=True`** | 覆盖文件里已有的值（逐键生效，无全局开关） | 显式改值 |
| **进程退出** | OnConf 自己 `sync()` 一次，兜底 | 无需调用 |

**与旧引擎最直观的一处不同**：旧引擎"写只记一笔、退出时统一落盘"，**新引擎每次调用即落盘**。
故"攒批"这件事不再存在，`sync()` 退化成"要文件立刻一致时显式调一次"。

## 4. 写入方向：代码 → 文件

```python
conf("core.log.level", "WARNING")  # 声明（第一次）
conf("core.log.level", "DEBUG")  # 文件里已有值 ⇒ 尊重文件，不覆盖（op=skip）
conf("core.log.level", "DEBUG", force=True)  # 强写：这一笔就是要改
```

**改值走配置文件**（人编辑是改值的正路），代码里要硬改必须显式 `force=True`。
`force` 只对**那一次提交**有效，逐键生效。

> `conf("k", force=True)` 不带值时会**静默走读分支**（OnConf 的读/写判据是"`value` 位有没有
> 给东西"，`force` 不参与判据）。要强写就必须给值。

## 5. 类型：声明期校验，读期透明

- `type=` **只在声明期**校验默认值一致性（`int` 不收 `bool`；`float` 不收 `int`——上游用的是
  `isinstance`，故"整数提升成浮点"这条旧口径**不再有**）；
- **读回来的值不做任何转换**：文件里写 `"8080"`，读回来就是字符串 `"8080"`。要整数在取用处
  自己写 `int(conf("…"))`——存储那组包装函数（`slot_bytes` 一类）正是这么收口的；
- **人手把文件里的值改成别的类型：不会当场报错**（旧引擎会在声明处报）。取用处的 `int(...)`
  会在那里炸——错误位置从"声明处"挪到了"取用处"；
- 值类型仍是 JSON 能表示的那几种：`int` / `float` / `bool` / `str` / `list` / `dict` / `None`。

## 6. 配置根与产物

```
config/
  settings.json          ← 值（使用者可改；顶部 $schema 指向词表）
  schema/settings.json   ← 词表（给 IDE 悬停与分发看的 JSON Schema）
  schema/settings.lock   ← 跨进程锁的握手点（运行期簿记，不入库）
  schema/settings.key    ← 专职写者的认证码（运行期簿记，不入库）
  logs/config.log        ← 引擎自己的日志（运行期簿记，不入库）
  theme/…  shapes.json   ← 与配置引擎无关的**手写**声明文件，只是同住一个目录
```

- **配置根有一个旋钮 `CAIRN_CONFIG`**：只给测试与部署重定向，**不是配置项**（它是"找到配置的
  办法"），值文件里不会出现它；
- **日志不落终端**：OnConf 每次读都留一行，默认去 `stderr`——那会淹掉命令行与测试输出，故内核
  把它指向 `<root>/logs/config.log`。日志口自己会建父目录，第一次写就把 `logs/` 建出来；
- **值文件文件名由 OnConf 探测**：`settings.yaml → settings.yml → settings.json → settings.toml
  → settings.env`，取第一个已存在的；都不存在时用 `settings.json`（本仓用的是 JSON）；
- `core.conf.sync()` 是给工具与测试的显式提交口；`conf` 本身**没有** `sync` 属性
  （`onconf.conf` 是个函数），旧写法 `conf.sync()` 不再成立。

## 7. 无生成脚本，但入库

两份产物**没有专门的生成脚本**：跑一遍程序就顺带生成。入库与否由
`tests/core/test_conf_projection.py` 拦——它拿**一个空目录里新生成的那一份**当基准比对入库的
那一份，故"声明改了、产物忘了重生成"会被它抓住。

参考页 `docs/reference/config.md` 由 `scripts/docgen.py` 生成：键 / 类型 / 默认值 / 说明读入库
词表，**声明处**由 AST 扫 `conf(...)` 调用点得出（只认字面量键；写在循环里的键显示 `—`）。

## 8. 语义变化（换引擎时逐条记住）

| 事项 | 旧（内建引擎） | 新（OnConf） |
|---|---|---|
| **重复声明同一键** | 启动即报错，报错带上先声明处的文件与行号 | **静默放行**：只更新词表，值文件不动 |
| **未知键（用户自加）** | 始终保留 | **提交点被清掉**（规则 1；该进程至少声明过一个键时） |
| **读到的值从哪来** | 值文件（文件压过默认值） | 值文件；读了就进内存缓存，**外部手改要等下一次提交才可见** |
| **类型不符** | 声明期 / 读期都当场报错 | 只在声明期校验默认值，读期透明 |
| **落盘时机** | 攒到退出（`atexit`）或 `sync()` | 每次调用即落盘（`flush_window=0`） |
| **`conf(k, v)` 返回** | 那一处写下的默认值 | **当前生效值**（文件里已有的优先） |
| **`file=` 值放独立文件** | 有（当时已无调用方） | **没有这个能力**，需要时另找办法 |
| **异常** | `core.exc` 的 `ConfigError` 族 | OnConf 的 `KeyNotRegisteredError` / `KeyHasNoValueError` / `TypeConflictError` / `ConfError` |

> **"未知键被清掉"这条最需要注意**：`config/settings.json` 的键空间**由声明定，不由文件定**。
> 想加自己的键，得先在代码里声明它；直接往值文件里塞一个键，下一次程序退出就没了。
> 反过来，**声明过的键、以及它的值与格式原样保留**——OnConf 的回写是文本级外科手术，
> 只动该动的那一个值区间。

## 9. 边界

- **声明归属各自**：使用方在自己包里声明（存储参数在 `core/storage/conf.py`，内核自己的在
  `core/params.py`）；`core/conf.py` 只负责定根与转发，不替其他包管理；
- **格式常量不进配置**：载体魔数、文件头长度、槽头布局这类改了会坏库的，留在实现处
  （`core/storage/pack.py` 的 `MAGIC` / `HEADER_SIZE` / `RECORD_HEAD_SIZE`）；
- **已落盘的东西不被新配置改写**：格长写进载体文件头，此后按文件头读；
- **引擎不是本仓的代码**：配置语义归 OnConf；内核侧只保留"配置根 + 转发 + 日志去向"这三件事。

## 10. 未做 / 已知限制（如实记）

- **OnConf 没法静态类型化**：它的 wheel 里没有 `py.typed`，故 `pyproject.toml` 给
  `onconf` 那一组开了 `ignore_missing_imports`。上游补上之后删掉那段；
- **上游两处待提 issue**：
  ① `EngineParams` 少了 `lock_timeout`，`conf(**engine)` 透传它会抛 `UnknownEngineParamError`；
  ② wheel 缺 `py.typed`（`pyproject.toml` 已声明 `Typing :: Typed`，实际却没生效）；
- **`conf(k)` 不重读磁盘**：读走的是执行者内存里的那本账，外部手改要等下一次真正提交才会被
  捞进来。内核的读点都在启动期，故当前不受影响；将来若出现"长驻进程且要持续看到外部改动"，
  得回到上游讨论（那是引擎的缓存口径，不是内核侧能补的）；
- **"重复声明即炸"这条看门能力随引擎一起没了**：要它得另找地方做（例如一道扫描 `conf(...)`
  调用点的 AST 门禁）；
- **不做"值来自声明还是被改过"的来源标记**；**值投影仍是单文件**。
