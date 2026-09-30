<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 术语表

> 项目里的词有**明确所指**，混用会读错代码。这里只收"读了会误解"的词；
> 定义以代码与 `docs/architecture/*.md` 为准，本表只是索引。

## 存储（L0）

> 这一节是**现状**：与 `docs/architecture/storage-design.md` 和 `py_src/core/storage/` 一一对应。

| 词 | 含义 | 不是什么 |
|---|---|---|
| **vault** | 库根目录：一个索引库 ＋ 若干 hub 目录（路径约定在 `core/init.py`） | 不是"保险箱"式的加密容器 |
| **hub** | `<root>/<hub>/packs/`：装若干载体；hub 名即地址（目录名） | 不是领域分区；代码里曾叫 bucket |
| **格 Slot** | 载体内的定长分配与定位单位；**一条记录至少占一格**，位置即 `(头格, 末格)` | 不是"格内偏移"（那是作废的旧模型） |
| **块 Block** | 存储单元；`id` ＋ `body`（当前实现只这两样，属性面随领域层再长） | 不是"文件" |
| **body** | 块的**载荷**，按内容地址进内容记录（同内容只存一份） | 不是正文文本（正文是 note 的 body 内层） |
| **记录 record** | 载体里的一条自框定记录：总长 ＋ 校验和 ＋ ID 段 ＋ 载荷 | 不是数据库的"行"（"行"指 `block` / `body` 表里的那一行） |
| **内容记录 / 块记录** | 前者载荷即 body、身份按内容签发；后者载荷是指针、身份是块自己的 | **各进一张表**（`body` / `block`），判据在载荷里有没有保留键 |
| **checksum** | 记录头里的载荷摘要（`sha256` 十六进制）；与 ID 的摘要形态同源 | 不是身份 |
| **ID** | 载荷与块的身份证：`value_uuid`（`uuid4`，比较有效）＋ `value_hash`（`sha256`，去重有效） | 不是裸字符串；也不是旧的 `ValueUuid` / `ValueHash` / `Id` |
| **地址 address** | 即摘要形态凭证，回答"是哪份内容" | 不是物理坐标 |
| **载体 pack** | 追加写的载体文件，随机命名、定长格、写满封口 | 不是"包管理器"的包 |
| **索引库 Index** | `<root>/catalog.db`：hub 登记、身份到位置的定位；**可重建的投影** | **不是真源**（真源是载体） |
| **类型登记** | 类型定义时记下"它用哪张表、持有哪些 ID 字段"（`registry.py`）；表的形状由它现算 | 不是运行期扫描全书 |
| **表自诞生** | 类型 → 登记 → 表声明 → `config/tables.yaml` → 建库那条链（L0 篇 §8.2.1） | 不是"手工建表"（那一步在这条路上没有位置） |
| **body_ref** | 块记录载荷里指向 body 的**两套凭证**（保留键 `\x00cairn.body_ref`） | 不是物理坐标；也不是只带摘要的旧写法 |
| **巡检 / 处置** | `patrol()` 只报告、`repair()` 只补不删（六类发现见 L0 篇 §8.7） | 不是重建（重建遇错即抛，巡检要看完） |

## 内核

> 这一节是**现状**（`py_src/core/`）。旧主轴的那套名字（`Core` / `Signal` / `ConfEngine` /
> `Managed` / 工具单元）随 2026-09-29 的重建整条删除（历史见 Git）。

| 词 | 含义 |
|---|---|
| **Kernel** | 内核装配：一个库根 ＋ 事件与存储两个引擎（`core/init.py`）；库的开关、维护入口都在这里 |
| **Bus / 事件总线** | 事件引擎：订阅、按注册顺序投递、异常隔离并交回失败清单（`core/event/bus.py`） |
| **Event** | 事件对象（冻结）：`type` / `source` / `subject` / `data` / `id` / `time`；字段名借 CloudEvents 口径 |
| **事件目录** | 当前会发出的事件类型常量（`object.put` / `object.deleted` / `budget.exhausted`，`core/event/catalog.py`），发布与订阅都引它 |
| **Storage** | 存储引擎：`store` / `load` / `body` / `drop` / `locate`（`core/storage/engine.py`） |
| **异常层** | `core/exc.py` 的层级：`CairnError` 兜底，存储 / 配置 / 属性各族细分；与日志的联动点在 `Bus` 的失败钩子 |
| **配置 conf** | `core/conf/` 的声明引擎：声明即事实（声明期校验、类型判据），值落单份值文件 | 不是配置文件本身；取用点不抄默认值 |
| **属性 attr** | `core/attr/` 的块字段声明（`attr[str]` 标注才落盘），按属性查询走可重建索引 | 不是数据库列定义 |
| **命令面 Api** | `core/api.py` 的方法表：内核短面暴露给边车 / CLI / 测试 | 不是 RPC 框架，也不含界面代码 |
| **表声明** | `TableSpec` / `Declaration`：表名、列、类型、约束、索引、重建档；建表语句由它编译 |
| **重建档 Tier** | 表级只有两项：`DERIVED`（可重建，必写来源）/ `SOURCE`（真源在库内，禁写来源） |

## 领域（意图：`feature` 待重建；note 落点 `py_src/model/note/` 新建中）

> 以下多为**当前没有代码**的目标形态（`py_src/model/note/` 只有骨架，内容随设计落地补齐）。

| 词 | 含义 | 不是什么 |
|---|---|---|
| **域 Domain** | **管理型对象**：单例、无 ID，管机制与策略（`Note` / `Project`） | 不是数据 |
| **数据（`XxxData`）** | **`Block` 子类**，有 ID，纯载体 + 读视图 | 不是域 |
| **`Kind`** | 类型词表（plain `Enum`，值即落盘字符串，如 `notedata`） | 不是旧 `cairn.<域>.<类>` 命名空间 |
| **note body** | 正文 = **行序列**（`list`），一元素 = 一行 / 一块，带稳定行 id | 不是字符串 |
| **style** | **非对称覆盖层** `{行id: [{区间: Style}]}`；行内区间可叠加，规范化为不重叠、有序、去默认 | 不是行属性 |
| **关系 Relation** | **由块自己表达**（块说它有哪些关系）；库只做索引，索引尚未设计、不预埋 | 不是字段；也不再是"一等 DB 行"（`edge` 表已于 2026-09-30 删除） |

## 界面（意图：Tauri 壳 + Web 前端）

> 以下多为**当前没有代码**的目标形态；工程落点是 `app/`（Tauri 壳 + Web 前端）。

| 词 | 含义 |
|---|---|
| **ui_tools** | Qt 时代的界面**工具箱**（声明树 / 编译 / 绑定 / 模型 / 主题）：层名已随 Qt 作废，职责由前端共享组件承担 |
| **App** | 应用**组合根 / 编排层**：组合内核 + 领域 + 界面；Python 侧入口在 `py_src/app/`（现仅边车），界面侧是 Tauri 壳 |
| **Facet** | 一个域的整套 UI 定义（分析器 + 组织器 + 包装器三合一），交给 App 编译挂载（Qt 实现已作废，去留待定） |
| **Slot** | App 根结构里的**命名槽位**（`expects=` 声明等谁的哪个部件；同上，待定） |
| **token / Theme** | 外观令牌**封闭词表**（唯一真源 `config/theme/tokens.json`）→ `gen:tokens` 生成 `tokens.css`，`check:tokens` 防漂移；组件只引用 `token.*`，禁硬编码 |


## 工程

| 词 | 含义 |
|---|---|
| **企业级-ε** | 本项目的质量口径：企业级再降半档（strict 类型 / ruff ALL / warning 零容忍 / 覆盖率 ≥80%） |
| **记忆 memory** | `.agents/skills/memory/references/`：**决策**（一个主题一文件、只写现状态）与**进度**（只记未做），可变活文件 |
| **规则 rules** | `.agents/skills/rules/references/`：约束与红线，按场景分发 |
| **REUSE.toml** | 集中声明**装不下 SPDX 头**的文件许可（采用 REUSE 的**数据格式**，工具自研） |
