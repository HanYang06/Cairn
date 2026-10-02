<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 快速开始

!!! warning "当前没有可用的界面"

    Cairn **尚未发布**（`0.0.1` / pre-alpha）。桌面壳（Tauri + Web 前端，`app/`）已立项，
    边车与转发口已接线，但功能远未齐备。内核（`py_src/core/`）可用；
    领域层（`py_src/model/note/`）只有形状与载体，**载荷的规范化字节层尚未落地**
    （[L0 存储设计 §11](../architecture/storage-design.md#11-未落地与预留)）。

## 1. 准备环境

需要 **Python 3.13** 与 [`uv`](https://docs.astral.sh/uv/)：

```powershell
git clone https://github.com/HanYang06/cairn.git
cd cairn
uv sync                 # 建立 .venv 并装齐依赖（不含任何 Qt 组件）
```

## 2. 运行内核

内核不依赖 Qt，可直接调用。库根由调用方显式给出：

```python
from core.init import Kernel
from model.note.types import NoteGroup

with Kernel.create("vault") as kernel:  # 建库并装配；已有库改用 Kernel.open
    group = NoteGroup()  # 零参构造：块自己现签一个身份
    group.title = "待整理"
    group.notes.extend(["n1", "n2"])

    ident = group.save()  # 落盘，返回块身份 ID
    print(ident.value_uuid, ident.in_pack_slot)  # uuid4 是这个身份 / 段列表是它占的槽

    fetched = NoteGroup.fetch(ident)  # 按身份读回同一个类
    print(fetched.title, fetched.notes)

    print(kernel.engine.index.tables())  # 库里有哪些身份表
```

要点：

- **写由块自己发起**：`group.save()`。装配处（`Kernel`）**没有 `store` 方法**——
  落点由类体上的 `Attr` / `Body` 声明决定，命令面里放一个 `store` 就绕过了这一条。
- **一个块分两个域**：属性进**属性槽**（可原地覆盖、不进历史）、正文进**正文槽**
  （只追加、按内容摘要去重、旧世代记进库里那一列，保留世代数取 `body.history.depth`）。
  两个域同处一段位置段：**正文槽在前、属性槽在后**，而属性槽那一段另记一列
  （`attr_in_pack_slot`），故切分不靠次序推。
- **索引库是权威视角**：`<root>/catalog.db` 装身份、位置与正文历史；
  `<root>/<hub>/packs/*`（载体）**只装值**，载体上不写一个字节的身份。
  **没有顺扫重建**，索引库丢失即身份与位置丢失。
- **本地不加密**，明文落盘；加密只作用于传输与远端副本（当前未实现）。
- **未落地的缺口**：`NoteData.lines` 里放 `NoteLine` 对象**存不下去**——
  `cbor2` 编不出 dataclass，领域载荷的规范化字节层（`py_src/model/note/format/`）没有实现。
  今天能往返的是标量属性与纯 JSON 值（如 `NoteTag.entries` 的 `dict[str, list[str]]`）。

## 3. 运行测试

测试不需要任何外部服务，全部使用临时本地库：

```powershell
uv run pytest                                        # 全部（含覆盖率）
uv run pytest tests/core/test_engine.py -x           # 单个文件
uv run pytest -k "conf" -x                           # 按名字筛
```

## 4. 运行桌面壳（实验性）

```powershell
pnpm --dir app tauri dev
```

- 需要 Rust 工具链与 Node / pnpm。
- 壳经边车接内核：壳以 `python -m app.sidecar <库根>` 起 Python 进程；
  解释器与模块路径由 `CAIRN_PYTHON` / `CAIRN_PYTHONPATH` 指定，库根由 `CAIRN_VAULT` 指定
  （未设置时用工作目录下的 `vault/`）。
- 功能未齐备：当前接通的是命令面与通知方向，界面功能仍在建设中。

## 5. 下一步

- 想改代码 → 「[参与开发](development.md)」与「[约定与红线](conventions.md)」
- 想看设计 → 「[架构索引](../architecture/index.md)」；
  L0 存储以「[L0 存储设计](../architecture/storage-design.md)」为准
- 想查某个类 / 函数的准确签名 → 「[API 参考](../api/index.md)」
