<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 内核（Kernel）

> 内核（`src/core/`）是桌面端与服务端的**公共底座**：底层同构，上层不同。
> 本文是**现状总览**；存储细节以 [`storage-design.md`](./storage-design.md) 为唯一事实来源，
> 旧主轴（`Core` / `Signal` / 对象主干 + 事件解析器）的规格见
> [`kernel-spec.md`](./kernel-spec.md)——**那一套已作废，仅存档**。

状态：**现行**（2026-09-29 按重建后的实现回写）。

## 0. 原则

1. **Qt-free、传输无关**：内核不认识 Qt（桌面）也不认识 WebSocket（服务端）。两端各自适配。
2. **通知层 ≠ 持久层**：事件是瞬时通知，不进存储；要追溯的是领域活动日志（另一套，属领域层）。
3. **提交后通知**：任何对外通知都在数据落盘之后发出，监听者看到的永远是已提交状态；
   通知失败不影响写入（失败清单交回调用方，并可接上日志）。
4. **不假装存在**：没有调用方的机制不建（如对象管理表），写不出重建来源的表必须标 `SOURCE`。

## 1. 装配：`Kernel`

内核只有一个入口（`core/init.py`），它管三件事：**库的开关**（路径约定只在这里定：
`<root>/catalog.db`、`<root>/<hub>/packs/`；`open()` 不建东西、`create()` 是显式动作）、
**引擎挂载**（事件总线与存储引擎）、**维护入口**（巡检与处置是整库动作，不是某一次写入）。

| 属性 | 是什么 |
|---|---|
| `index` | 已对齐的索引库（`Index`） |
| `bus` | 事件总线（`Bus`） |
| `storage` | 存储引擎（`Storage`） |
| `root` / `catalog_path` | 库根与索引库路径 |
| `policy` / `logger` | 载体策略（格长与封口线）、内核日志器 |

短面：`store`（可带块自己声明的 `attrs`）/ `load` / `drop` / `locate`；
维护：`patrol()` / `repair(report)`。

## 2. 事件引擎

- **只做扇出通知，不做决策。** 内核里**没有** `EventParser`、没有"解析包 → 决定做什么"的中介者：
  命令路径走显式调用（同一个进程里，直接调比发包+猜意图又快又清楚）。行业依据与重启条件见
  记忆的「事件层只做扇出通知」。
- **事件对象**（`core/event/events.py`）：冻结的 `Event`，字段 `type` / `source` / `subject` /
  `data` / `id` / `time`；命名借 CloudEvents 口径，**不代表实现该规范**。
- **总线契约**（`core/event/bus.py`）：按**注册顺序**投递；某个订阅者抛错不中断其余订阅者，
  失败清单由 `emit` 交回并调用可选失败钩子；订阅句柄可 `cancel()` 或作上下文管理器；
  同一处理器重复订阅只算一份。**不做弱引用自动摘除**（那会让"发了没人收到"变成最难查的故障），
  **不加锁**（内核约定写路径单线程，跨线程回投由适配层排队）。
- **事件目录**（`core/event/catalog.py`）：当前两条——`object.put` / `object.deleted`。
  发布方与订阅方都引常量，避免两处字面量分叉。

## 3. 存储引擎

`Storage`（`core/storage/engine.py`）把块落成**两条记录**：内容记录（载荷即 body，身份按内容签发，
故同内容只存一份）与块记录（载荷是指向 body 的**两套凭证**的指针，身份是块自己的）。
读回是"两条一拼"：块身份 → 读块记录 → 取指针 → 按地址读内容记录。
**块自己声明的属性跟着块记录走**（同一载荷里的另一个保留键）：不进 body、也不落库列，
故它随块的身份一起变，且顺扫可还原。
两条记录各进**各自的表**（`body` / `block`），行层读写见 `storage/rows.py`；
表的形状由类型登记现算（`storage/registry.py` / `tablegen.py`），
细节（格模型、记录头、索引库、巡检）全在 [`storage-design.md`](./storage-design.md)。

## 4. 异常与日志

- 异常是一层**声明**（`core/exc.py`）：`CairnError` 兜底，存储侧一族细分
  （`RecordFormatError` / `SlotError` / `HubNotFoundError` / `HubShapeError` /
  `IndexNotFoundError` / `IndexSchemaError` / `TableDeclarationError` / `ObjectNotFoundError`）。
  调用方按类型分流，不靠字符串认错。
- **联动点是总线**：`Kernel` 给 `Bus` 装一个失败钩子，把处理器抛的错记进 `cairn.kernel` 日志——
  通知层的异常既不回流发布者，也不消失。

## 5. 预留

| 项 | 状态 |
|---|---|
| 对象管理表 | **预留**：它要服务"按对象收发事件"，而那条路（中介者）已明确不做，故只把引擎挂在属性上 |
| 配置引擎 | 不在内核装配里：`src/core/conf/` 由作者另行推进 |
| 任务与进度（长操作、取消） | 预留（随上层重建再定）：`patrol` / `rebuild` 这类整库动作将来要进度 |
| 应用上下文（多库注册、事件聚合） | 预留（服务端多租户成稿时定义） |
