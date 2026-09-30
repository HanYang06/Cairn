<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 领域层：定义与扩展约定

> 承接 [`storage-design.md`](./storage-design.md)（L0 桶 / 块）与 [`data-model.md`](./data-model.md)（对象模型总纲）。
> 本文定义**领域层是什么**、怎么扩展，以及日志的分层约定。

状态：**草案 v0.4**（2026-09-22 按内核重构定向回写；旧 `cairn.<domain>.<kind>` 命名空间与「五域」表述作废）

> **2026-09-22 方向更新（以 [`kernel-spec.md`](./kernel-spec.md) v1.2 为准）**：
>
> - **域服务经门户接入**：`class Note(Domain)` + `Note(core)`（构造即接门户、登记进实例管理）；
>   旧的 `Domain.bind(signal)` / `_signal` / 地址树**已删除**。域的对外面是门户上的
>   **行动作**（`@action` 标注，解析器扫描成表）与**多播声明**（`Topic`）。
> - **`name` 改为域自报短名**（`note` / `project`），**不再是模块路径**——它是门户上的**寻址键**。
> - **字段标注 `Attr` / `Data` 已归工具单元** `core/tool/attr.py`（不属存储层；`core.types` 不再转出）。
> - **"域 / 数据两分支"仍是现状描述**，但**不再由"是否继承 `Block`"定义对象身份**：
>   对象与块分离是 M4 的活（kernel-spec §5 剥离项）；本节表格按现状记录，方向以规格为准。
> - 跨模块行为**必须经门户**（`core.portal`）；过渡期域服务仍读 `core.storage.bucket`（M4 收口）。

---

## 1. 两条线：域 与 数据

`feature/` 只有两拨，先分这个，再谈细分：

| 大类型 | 是什么 | 代码 | 身份 | 位置 |
|---|---|---|---|---|
| **域** | 管理型对象：管配置、给 UI API | `Domain` 子类 | 单例、**无 ID** | `feature/note`、`feature/project` |
| **数据** | 存储数据结构（块） | `Block` 子类 | **有 ID**（oid / gid） | `feature/shared/`：`canvas` / `asset` / `group` |

- 域**不落盘**，也不产生第三态；它只"管理"数据。
- 数据是**载体**（字段 + 读视图）；编辑操作在**域服务**（`service.py`）里，以 data 为首参。
- 数据类可以有自己的轻量构造入口（如 `AssetData.create`），但它**不是域**。
- 共享设施同处 `feature/shared/`：`signature`（值）/ `provenance`（派生查询）/
  `base`（错误 / 标签）/ `kinds`（类型词表）。（**关系**没有专属共享件：它由块表达，索引未设计。）

## 2. 类型词表 `Kind`

```python
class Kind:
    class Feature(Enum):  # 域
        Note = "note"
        Project = "project"

    class Data(Enum):  # 数据（落盘的块类型）
        Notedata = "notedata"
        Projectdata = "projectdata"
        Canvas = "canvas"
        Asset = "asset"
        Group = "group"
```

- plain `Enum`、**值即落盘字符串**（无 `cairn.` 前缀）；第三方类型用自有前缀字符串（开放世界）。
- 类型表（`core/types/kind.py`）按值归一（`type_name`），枚举与字符串可互换。
- **旧命名空间约定 `cairn.<domain>.<kind>` 作废**；core 内部三型（`block` / `part` / `index`）同为短名。

## 3. 域的标准形

```python
class Note(Domain):
    type = Kind.Feature.Note  # 身份（缺省 = 类名小写）
    name = "note"  # 门户上的**寻址键**（短、稳定、唯一；缺省 = 模块路径）
    data = (NoteData, AssetData, CanvasData, GroupData)  # 本域用到的数据类（body 免列）
    light = [NoteData]  # 最小数据单元（可多个）

    def __init__(self, core: Core) -> None:
        super().__init__(core)  # 接门户：登记进实例管理 + 记住门户
        self.core = core
```

- `name`：门户上的**寻址键**（`core.get("note")` / 事件包的 `role` 命中它）；**领域不写显示名**
  （显示名是 UI 的事）。缺省填模块路径，域应自报短名。
- `data`：声明本域用到的数据类；`light`：最小数据单元——UI 的 `Show` 据此归集显示素材。
- 域服务方法（`@action` 或普通方法）**以 data 为首参**；资源本体在数据块里，域只给语义与策略。
- 跨模块调用经**门户**：`self.changed.emit(self.portal, data.oid)`；`@action` 供解析器扫描成行动作表。
- 红线：**不改 `Block` 顶层字段**；**不 import 兄弟域**（跨域协作归 App）。

## 4. 数据的标准形

```python
from core.tool.attr import Attr  # 字段标注工具（不属存储层）


class NoteData(Block):
    type = Kind.Data.Notedata
    body: NoteBody = NoteBody()  # 结构化 body；裸 body 用 BodyField()
    title: Attr[str | None] = None  # 注解即类型、右边即值（自动字段）
    tags: Attr = Attr(factory=dict, coerce=normalize_tags)  # 显式描述符
```

- 容器分工：**内容** `body`（进内容池，按 `body_hash`＝落盘负载哈希去重）/ **描述** `attrs`（随块行存）。
- 扩展方式只有两种：**加一个 `type` 子类**、或**给已有类加字段**（`Attr` / `Data` / `Body`）。
- 关系**由块自己表达**（块说它有哪些关系）；库只做索引，索引尚未设计（2026-09-30 定，不预埋）。
- 组：域身份 `gid`（≠ 块 `oid`）+ 有序子项 `group` 列表（可嵌套）；另存 `contains` 边做反查。
- 签名为**复合值**（`Signature`），落在 attrs；画板值类型（`Graphic` / `Paint` / `Link`）同属数据描述。

## 5. 大内容：交给存储的分片

- 分片是**存储**的活：小则一块，大则切成 `part` 块 + 一个 `index` 索引块，返回可引用的稳定身份。
  **预留**：粒度（`storage.block.max_bytes`）与词表（`PART_TYPE` / `INDEX_TYPE`）已定，
  块面尚未接上，见 [`storage-design.md`](./storage-design.md) §6.3 / §12。
- 分片块**不做块级去重**；去重只发生在领域对象这一层（同 body 的内容面只存一份是存储给的）。

## 6. 日志：诊断 vs 活动（两层，互不混淆）

### 6.1 诊断日志（自带，全库统一）

- core 只用 `logging.getLogger(__name__)` 发事件，**绝不配置** handler / level / 格式。
- 命名空间天然分层：`core` / `feature` / `ui_tools` / `app`。
- **配置在应用层**（UI 启动时）；库自身不设默认输出。

### 6.2 活动 / 审计日志（领域自有，持久化）

- 这是**数据，不是 logging**：持久化、可（选择）加密的事件记录，落在块桶里。
- **各领域一套独立 schema，绝不混存**；事件 = 普通块，类型用短名（如 `project.event.<名>`）。
- 未来 P2P 的同步 / 审计轨迹也建立在这一层。

## 7. 待定

1. 领域事件类型命名与保留策略。
2. 应用层日志配置是否暴露给用户（级别、轮转）。
