<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 术语表

> 项目里的词有**明确所指**，混用会读错代码。这里只收"读了会误解"的词；
> 定义以代码与 `docs/architecture/*.md` 为准，本表只是索引。

## 存储（L0）

> 这一节是**现状**：与 `docs/architecture/storage-design.md` 和 `src/core/storage/` 一一对应。

| 词 | 含义 | 不是什么 |
|---|---|---|
| **vault** | 库根目录：一个索引库 ＋ 若干 hub 目录（路径约定在 `core/init.py`） | 不是"保险箱"式的加密容器 |
| **hub** | `<root>/<hub>/packs/`：装若干载体；hub 名即地址（目录名） | 不是领域分区；代码里曾叫 bucket |
| **格 Slot** | 载体内的定长分配与定位单位；**一条记录至少占一格**，位置即 `(头格, 末格)` | 不是"格内偏移"（那是作废的旧模型） |
| **块 Block** | 存储单元；`id` ＋ `body`（当前实现只这两样，属性面随领域层再长） | 不是"文件" |
| **body** | 块的**载荷**，按内容地址进内容记录（同内容只存一份） | 不是正文文本（正文是 note 的 body 内层） |
| **记录 record** | 载体里的一条自框定记录：总长 ＋ 校验和 ＋ ID 段 ＋ 载荷 | 不是数据库的"行"（"行"指 `record` 表那一行） |
| **内容记录 / 块记录** | 前者载荷即 body、身份按内容签发；后者载荷是指针、身份是块自己的 | 二者同表，判据在载荷里有没有保留键 |
| **checksum** | 记录头里的载荷摘要（`sha256` 十六进制）；与 ID 的摘要形态同源 | 不是身份 |
| **ID** | 载荷与块的身份证：`value_uuid`（`uuid4`，比较有效）＋ `value_hash`（`sha256`，去重有效） | 不是裸字符串；也不是旧的 `ValueUuid` / `ValueHash` / `Id` |
| **地址 address** | 即摘要形态凭证，回答"是哪份内容" | 不是物理坐标 |
| **载体 pack** | 追加写的载体文件，随机命名、定长格、写满封口 | 不是"包管理器"的包 |
| **索引库 Index** | `<root>/catalog.db`：hub 登记、身份到位置的定位、关系边；**可重建的投影** | **不是真源**（真源是载体） |
| **body_addr** | 块记录载荷里指向 body 的地址（保留键 `\x00cairn.body_addr`） | 不是物理坐标 |
| **巡检 / 处置** | `patrol()` 只报告、`repair()` 只补不删（六类发现见 L0 篇 §8.7） | 不是重建（重建遇错即抛，巡检要看完） |

## 内核

> 这一节是**现状**（`src/core/`）。旧主轴的那套名字（`Core` / `Signal` / `ConfEngine` /
> `Managed` / 工具单元）随 2026-09-29 的重建整条删除，见「[内核规格](../architecture/kernel-spec.md)」的存档说明。

| 词 | 含义 |
|---|---|
| **Kernel** | 内核装配：一个库根 ＋ 事件与存储两个引擎（`core/init.py`）；库的开关、维护入口都在这里 |
| **Bus / 事件总线** | 事件引擎：订阅、按注册顺序投递、异常隔离并交回失败清单（`core/event/bus.py`） |
| **Event** | 事件对象（冻结）：`type` / `source` / `subject` / `data` / `id` / `time`；字段名借 CloudEvents 口径 |
| **事件目录** | 当前会发出的事件类型常量（`object.put` / `object.deleted`），发布与订阅都引它 |
| **Storage** | 存储引擎：`store` / `load` / `body` / `drop` / `locate`（`core/storage/engine.py`） |
| **异常层** | `core/exc.py` 的层级：`CairnError` 兜底，存储侧一族细分；与日志的联动点在 `Bus` 的失败钩子 |
| **表声明** | `TableSpec` / `Declaration`：表名、列、类型、约束、索引、重建档；建表语句由它编译 |
| **重建档 Tier** | 表级只有两项：`DERIVED`（可重建，必写来源）/ `SOURCE`（真源在库内，禁写来源） |

## 领域（意图：`src/feature/` 待重建）

> 以下都**当前没有代码**，是重建时的目标形态。

| 词 | 含义 | 不是什么 |
|---|---|---|
| **域 Domain** | **管理型对象**：单例、无 ID，管机制与策略（`Note` / `Project`） | 不是数据 |
| **数据（`XxxData`）** | **`Block` 子类**，有 ID，纯载体 + 读视图 | 不是域 |
| **`Kind`** | 类型词表（plain `Enum`，值即落盘字符串，如 `notedata`） | 不是旧 `cairn.<域>.<类>` 命名空间 |
| **note body** | 正文 = **行序列**（`list`），一元素 = 一行 / 一块，带稳定行 id | 不是字符串 |
| **style** | **非对称覆盖层** `{行id: [{区间: Style}]}`；行内区间可叠加，规范化为不重叠、有序、去默认 | 不是行属性 |
| **关系 Relation** | 一等 DB 行（`edge` 表）：`derived-from` / `references` / `contains` 等，用于引用拓扑 | 不是字段 |

## 界面（意图：`ui_tools` / `app` 待重建）

> 以下都**当前没有代码**。

| 词 | 含义 |
|---|---|
| **ui_tools** | 界面**工具箱**：声明树 / 编译 / 绑定 / 模型 / 主题。不认识领域 |
| **App** | 应用**组合根 / 编排层**：组合内核 + 领域 + UI，按平台发布 |
| **Facet** | 一个域的整套 UI 定义（分析器 + 组织器 + 包装器三合一），交给 App 编译挂载 |
| **Slot** | App 根结构里的**命名槽位**（`expects=` 声明等谁的哪个部件） |
| **token / Theme** | 外观令牌**封闭词表**（唯一真源）→ 编译为 QSS；组件只引用 `token.*`，禁硬编码 |


## 工程

| 词 | 含义 |
|---|---|
| **企业级-ε** | 本项目的质量口径：企业级再降半档（strict 类型 / ruff ALL / warning 零容忍 / 覆盖率 ≥80%） |
| **记忆 memory** | `.agents/skills/memory/references/`：变更 / 决策 / 进度，**可变活文件**，每条标日期 + 状态 |
| **规则 rules** | `.agents/skills/rules/references/`：约束与红线，按场景分发 |
| **REUSE.toml** | 集中声明**装不下 SPDX 头**的文件许可（采用 REUSE 的**数据格式**，工具自研） |
