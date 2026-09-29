<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# M1 · 门户与实例管理（落地计划）

> ⚠️ **已作废，仅存档（2026-09-29）**：这份计划的产物（`Core` 门户、实例管理、5 对象）
> 随 `refactor/clean-local-code` 整条删除。重建后的内核见 [`kernel.md`](./kernel.md) 与 `src/core/`。

> 依据 `docs/architecture/kernel-spec.md` v1.0。分支 `refactor/kernel-object-core`。
> 本文件是**施工计划**，写完 M1 后并入 `kernel-spec.md` 或删除。

---

## 1. 目标（M1 定义）

1. **`Core` 成立**：能力提供 + **对象实例管理**（5 对象里唯一持实例者）。
2. **`Conf` 经门户可达**：从空壳长成真模块，且只能经门户取。
3. **`Vault` 解散**：持桶归 `Storage`，能力与实例管理归 `Core`。
4. **跨模块直连逐条归位**：一切经门户。

---

## 2. 新目录：`core/kernel/`（门户层）

门户层独立成包，与存储层（`core/storage`）平级；`M2` 后 `core/signal` 清空删除。

| 文件 | 内容 | 状态 |
|---|---|---|
| `core/kernel/__init__.py` | 门户导出面 | 新增 |
| `core/kernel/event.py` | `Event`：门户唯一入口（动作 + 行为描述 + 承载体 + 可辨识信息） | 新增 |
| `core/kernel/signal.py` | `Signal` **解析器**：只解析包、只决策；`Subscription` 投递 | 新增（`Subscription` 自 `core/signal/events.py` 迁移） |
| `core/kernel/storage.py` | `Storage`：对象进 / 出（**包** `Bucket`，不是替代） | 新增 |
| `core/kernel/core.py` | `Core`：门户 + 实例管理（`install` / `get` / `has` / `instances`） | 新增 |
| `core/kernel/conf.py` | `Conf`：参数真源（薄封装，先覆盖现有常量 + 可设键） | 新增 |
| `core/kernel/action.py` | `action` **标注工具**（无逻辑的静态标注，供解析器辅助） | 新增 |

**放置原则**（并回写 `kernel-spec.md` §3）：`core/kernel/` 是门户层；`core/storage/` 是存储层；
`Attr` 所在的字段标注不属存储，M3 一并归位到工具侧。

---

## 3. `Event` 的形状（M1 版）

```
Event:
  id        # 可辨识信息（ULID）：网络落地去重 / 排障用；不是持久化身份
  action    # 动作：要发生 / 已发生的是什么（动词）
  role      # 承载体指向谁：实例管理里的名字（可空）
  body      # 行为描述：该动作的形态与参数（dict）
  carrier   # 承载体（可选）：随事件走的非对象载荷（bytes / 流）
  at        # unix ms
  origin    # 来源标识（本机 / 对端），M2 用
```

- **对象实例不随包走**：`role` 是可辨识信息，实例由 `Core` 取出。
- `to_data()` / `from_data()`：**自包含可编解码**（M1 用 `core.storage.canonical`）。

---

## 4. `Signal` 解析器的行为

- `parse(event) -> Outcome`：唯一逻辑所在。解析 → 决策 →（调用 / 广播 / 反馈）。
- **决策表（确定性，M1）**：
  1. `role` 为空 → 广播（多播）：所有订阅者收到包；订阅者异常**隔离**。
  2. `role` 有值 → 定位实例（`Core.get`），按 `action` 找到**行动作**（该服务上被 `action` 标注的方法）→ 单播调用；**异常透传**。
  3. 目标实例不存在 / 动作不存在 → 抛 `SignalError`（fail-loud，不再有"未绑定直调"退路）。
- `emit(event)`：门户唯一入口；`parse` 是它对内的一步。

---

## 5. `Core` 的实例管理

- `install(name, instance, *, role=None)`：登记实例；`action` 标注在一次静态扫描中转成**行动作表**。
- `get(name)` / `has(name)` / `instances()` / `release(name)`。
- `portal`（`Signal`）/ `conf` / `storage` 三个能力入口。
- **实例的唯一权威**：不存在第二处持有实例的地方。

---

## 6. 迁移与清理（M1 一次做完）

| 现有 | 动作 |
|---|---|
| 5 个域服务的 `Domain` / `@action` / `Topic` | 改为 `Core.install(...)` + `@action` 标注 + `__class__` 静态扫描 |
| `Feature(vault, vault.signal)` | 改为 `Feature(core)`：把域服务 `install` 进门户 |
| `app/win/windows/app.py` 的 `Vault.load/create` | 改为 `Core.open(path)` |
| `ui_tools/core/session.py` 消费 `vault.signal` | 改为消费 `Core.portal` |
| `core/vault.py`（`Vault`） | **删除** |
| `core/signal/`（旧门户：bus / service / events） | **删除**（`Subscription` 迁入 `core/kernel/signal.py`） |
| `core/types/errors.py` 的 `VaultError` | 删除（按 §1.5 无容身之处） |
| `tests/**` 引用旧门户 | 同步迁移 |

---

## 7. 验收（每片都跑）

```
uv run ruff check . && uv run ruff format --check .
uv run mypy src tools
uv run pytest
```

M1 完成时：全绿；架构测试仍断言 `ui_tools` 不 import `feature` / `core.storage` / `core.vault`。

---

## 8. 分片（每片一个提交，供审查）

1. **片 1**：新增 `core/kernel/`（`event` / `signal` / `storage` / `conf` / `action` / `core`）+ 单测；
   旧门户**暂留**，全绿。（本片结束时新旧并存，属过渡态，**片 2 必须清掉**。）
2. **片 2**：迁移域服务与 App 到门户；删除 `Vault` 与 `core/signal`；全量测试迁移；全绿。
3. **片 3**：架构文档回写（`kernel.md` / `ui-kernel.md` / `storage.md` / `domains.md`）与记忆收尾。

---

## 9. 本片待作者确认的两处（不阻塞开工，先按此实现）

- **`Feature`（App 组合根）**：新形态是"把域服务 `install` 进门户的装配清单"，从 `app/` 与 `core/` 都看不见它——它是 App 侧概念，不进内核。
- **`Domain` 基类**：M1 保留为**极简服务基类**（只声明 `name` / `type`），去掉 `bind` / `_signal` / 地址树耦合；若 M3 后无必要则删。
