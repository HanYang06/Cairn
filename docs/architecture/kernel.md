<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 内核横切设施

> 内核（`core`）是桌面端与服务端的**公共底座**：底层同构，上层不同。
> 本文件定义那些"两端都要、又必须与界面/传输解耦"的横切设施。

状态：**草案 v0.2**（事件已实现；任务、应用上下文为预留设计）

> **2026-09-22 方向更新（以 [`kernel-spec.md`](./kernel-spec.md) v1.2 为准）**：
> 内核主轴已改为「**对象主干 + 事件对象**」。本文 §1.6「通信主干 = 统一调用总线」**作废**：
>
> - 门户 = `core/kernel/`：`Core`（能力提供 + **对象实例管理**）+ `Signal`（**解析器**：
>   解析 `Event` 包 → 决策）。**内核逻辑只有这一处**（"信号处理器只解析包"）。
> - **事件是对象**（`Event`：动作 + 行为描述 + 承载体，近消息协议），**不进存储**；
>   单机是内存生命态，网络是数据流、到达即还原为对象。
> - §1 的"事件目录 / 订阅 API"是按**旧实现**写的：现在订阅的是**门户上的事件包**
>   （`core.subscribe` / `core.portal.subscribe`），存储事件只是"存储产生的某类包"
>   （`object.put` / `object.deleted`），**不再是内核事件目录的全部**。
> - 参数真源归 `core/conf`（`Conf`）；标注工具归 `core/tool`。旧门户 `core/signal` 已删除，
>   `Vault` 已解散（持桶归 `Storage`，能力与实例管理归 `Core`）。

---

## 0. 原则

1. **Qt-free、传输无关**：内核不认识 Qt（桌面）也不认识 WebSocket（服务端）。两端各自适配。
2. **通知层 ≠ 持久层**：事件与进度是瞬时通知；要追溯的是领域活动日志（另一套，见 [`domains.md`](./domains.md)）。
3. **提交后通知**：任何对外通知都在数据落盘之后发出，监听者看到的永远是已提交状态。

---

## 1. 事件 / 信号（已实现）

### 1.1 原则

- **类型化**：每种变更一个 frozen dataclass，继承 `Event`。
- **按对象操作发**，不按块发；批量导入需合并（见 §1.4）。
- **同步分发**：在发布者线程上调用处理器。UI 适配层负责排队回主线程。
- **异常隔离**：通知处理器抛错只记日志，绝不影响 `put`/`delete`；**单播命令则异常透传**（见 §1.6）。
- **不可重入**：处理器只许观察/入队，不得回调进 `Vault` 的写操作。

### 1.2 事件目录（当前）

| 事件 | 字段 |
|---|---|
| `ObjectPut` | `oid`, `type`, `seq`, `created`(新建/更新), `checksum`(内容签名，判变用) |
| `ObjectDeleted` | `oid` |

> 事件目录当前精简为这两个。旧的 `VaultUnlocked` / `VaultLocked` / `SpaceCreated` 已随
> 「本地不加密 + 无空间」删除（见 [`storage-design.md`](./storage-design.md) §7）。

### 1.3 订阅 API

```python
with vault.subscribe(handler) as sub:  # 全部事件
    ...
sub = vault.subscribe(handler, event_type=ObjectPut)
sub.cancel()
```

### 1.4 批量与合并（预留）

- 大导入 / 批量写入应通过 `Vault.batch()` 上下文，抑制逐对象事件，结束时发一条汇总事件（如 `BatchCommitted(count)`）。
- 未实现前，调用方需自行限频。

### 1.6 通信主干 `core/signal`（统一调用总线）

- `core/signal` 是**唯一主干**：`EventBus`（投递机制，已并入本包）+ `Signal`（总线，暴露 `core` / `feature`
  域容器）+ `Domain`（域服务基类：`@action` 单播 / `Topic` 多播）+ `Action` / `BoundTopic`。
- **静态挂载**：域容器由**组合根（App）**静态声明并 `signal.feature = …`；域经 `Domain.bind(signal)` 绑总线。
  **无字符串注册 / 无 `__getattr__` / 无运行时内省**（领域数量少且确定；插件化留待未来）。
- **单播**命令异常**透传**；**多播**通知异常**隔离**。
- `Vault.signal` 即主干；`Vault.events` 就是 `signal.events`（同一投递器）。

### 1.5 事件 vs 日志

| | 事件/信号 | 诊断日志 | 领域活动日志 |
|---|---|---|---|
| 性质 | 瞬时通知 | 诊断文本 | 持久化数据 |
| 消费者 | 进程内订阅者 | 开发者/运维 | 用户/追溯/同步 |
| 归属 | 内核 | 应用配置 | 领域层 |

---

## 2. 任务与进度（预留）

长操作（GC、`rebuild_index`、导入、将来的同步）需要**进度与取消**，UI 要进度条，服务端要作业管理。

### 2.1 任务抽象

```
Task:
  id: str
  kind: str                # "gc" | "index.rebuild" | "import" | "sync" ...
  total: int | None        # 未知总量时 None（不确定进度）
  done: int
  unit: str                # "blocks" | "objects" | "bytes"
  state: pending|running|succeeded|failed|cancelled
  cancel() -> None         # 协作式取消
```

### 2.2 任务事件（复用同一事件总线）

`TaskStarted` / `TaskProgress` / `TaskSucceeded` / `TaskFailed` / `TaskCancelled`。

### 2.3 取消语义

- **协作式**：长循环周期性检查 `task.cancelled` 并优雅退出。
- 取消不是回滚：已提交的写保持提交（保证原子性优先）。

### 2.4 接入点

`Vault.gc()`、`Vault.rebuild_index()`、未来的 `ImportService`、`SyncService`。

---

## 3. 应用上下文 / 配置（预留）

桌面端可能同时开多个库；服务端天然多租户。需要一个上层"应用上下文"，但**内核只提供最小原语**，不预设应用形态。

### 3.1 AppContext（上层，非内核）

```
AppContext:
  vaults: dict[name, Vault]     # 多库注册
  events: EventBus              # 应用级总线（可聚合各库事件）
  config: AppConfig             # 应用级设置
```

### 3.2 配置分层

| 层 | 位置 | 内容 |
|---|---|---|
| 应用级 | 各端自定（如 `%APPDATA%/cairn`） | 最近打开、主题、日志级别、监听地址 |
| 库级 | `vault/catalog.db` 的 `meta` 表 | 声明投影（开库时与程序声明比对） |

- 库级那份**不是可改的配置**：它由存储自己的配置声明展开而成（`config/settings/core/storage/`），
  开库时比对，不一致即报错。存储的参数（封口线、槽长、分片粒度）走**配置文件**，
  槽长随载体写进文件头（设计篇 §5.5–§5.6）。
- 早先设想的 `<vault>/cairn.toml` **未实现**（本地不加密后，KDF / 封装密钥等字段随之作废）。
- 应用级配置待 UI / 服务端出现时再定。
- **内核不读应用级配置**，只读库级。

### 3.3 多租户映射

服务端每个租户 = 一个 `Vault`；`AppContext` 负责注册与隔离，内核本身保持单库单写者语义。

---

## 4. 待定

1. `Task` 是内核原语还是上层设施（倾向：抽象放内核，调度/线程池放上层）。
2. `Vault.batch()` 的合并粒度与事件形态。
3. 应用级配置格式与位置（跨平台约定）。
4. 服务端多租户下的事件聚合与背压策略。
