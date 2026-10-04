<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Cairn · 巨石堆

> **本地优先的内容寻址对象池** —— 笔记、资产、项目，一台工作台。

一块块往上堆。

```text
文档站     https://hanyang06.github.io/cairn/
仓库       https://github.com/HanYang06/cairn
```

[![Architecture diagram of hanyang06/cairn](https://gitdiagram.com/hanyang06/cairn/diagram.png)](https://gitdiagram.com/hanyang06/cairn?utm_source=readme&utm_medium=picture)

## 定位

- **本地优先**：块是本体，应用只是消费者。数据落普通文件
  （`<root>/<hub>/packs/*.pack`，文件头 ＋ 一串定长格）＋ 一个索引库 `<root>/catalog.db`——
  **身份、位置与正文历史以索引库为准**，载体只装值。该口径见
  [块的组成与落点](docs/architecture/py_core/storage/block-parts.md)（2026-10-02 裁定，**同日落码**）。
- **三件套**：笔记、存储、项目管理。
- **桌面优先**：以 Windows 为主要平台，内核与打包保持跨平台能力。
- **内容寻址对象池**：正文按内容摘要去重、身份稳定寻址；**本地落盘明文**，
  加密只用于传输 / 服务端（尚未实现）。这是与其他笔记软件的根本分野。

## 现状

早期开发阶段，**尚未发布**（`0.0.1` / pre-alpha）。

- ✅ **存储层已按 2026-10-02 的裁定落码**：`py_src/core/storage/` 就是**两类槽**
  （属性槽原地覆盖、正文槽只追加）＋ **索引库为权威视角**（装身份、位置与正文历史）
  的现状实现，载体上不写一个字节的身份。测试与门禁此刻均通过。
- **重建中**：领域层（`py_src/feature/` 已删，新落点 `py_src/model/note/`）与界面
  （Tauri 壳与边车已接线，功能未齐）。
- 🔜 未做：回收的触发点（`sweep` 与 `reclaimable_bytes` 都已可用，但**没有调用方**）、
  检索、P2P / 服务端、打包与桌面入口。

**详细进度与取舍不在本文件**——事实源是代码本身与 `docs/architecture/**`；
存储子层的裁定见 `docs/architecture/py_core/storage/`。

## 快速开始

需要 **Python 3.14** 与 [`uv`](https://docs.astral.sh/uv/)：

```powershell
uv sync                 # 安装/同步依赖
uv run pytest           # 跑内核测试（桌面入口尚未就绪）
```

内核不依赖 Qt，装配在 `core.init` 的 `Kernel`：库根由调用方显式给出（`Kernel.create(root)`
建库、`Kernel.open(root)` 打开已有库），**内核侧没有库路径旋钮**；桌面壳侧由 `CAIRN_VAULT`
指定库根，`CAIRN_PYTHON` / `CAIRN_PYTHONPATH` 指定边车的解释器与模块搜索路径
（见 `app/src-tauri/src/lib.rs`）。目标用法见 [快速开始](docs/guides/quickstart.md)。

开发库默认 `<repo>/vault/`（已 gitignore）；壳未设 `CAIRN_VAULT` 时就用它。

## 架构

| 目录 | 职责 |
|---|---|
| `py_src/core/` | L0 底座：事件引擎 / 存储引擎 / 配置引擎 / 异常层；**Qt-free、传输无关** |
| `py_src/model/` | 领域层：`feature` 已删，新落点在 `model/note/`（随存储重写收敛） |
| `py_src/app/` | Python 侧入口：边车（`app/sidecar.py`）已在，命令行与命令面**待落地** |
| `app/` | 桌面外壳：Tauri 工程（`app/src/` React 前端 · `app/src-tauri/` Rust 壳）**功能待落地** |
| `assets/` | 品牌素材单一真源（logo / 启动图 / Tauri 与安装包图标都从这里取） |

Python 顶层包一律去 `cairn.` 前缀（如 `from core.storage import …`）；源码根叫 `py_src/`
（不叫 `src/`：与 `app/src/` 撞名）。逐层红线见 [`AGENTS.md`](AGENTS.md) 的「架构分层」。

分层红线与约定见 [约定与红线](docs/guides/conventions.md)；设计事实来源是 `docs/architecture/**`
（这批页待重写，此刻在库的只有配置引擎与 UI 主题两页）。

## 开发

```powershell
uv run pytest                      # 全部测试（无需外部服务，全部用临时本地库）
uv run ruff check .                # lint（--fix 自动修）
uv run mypy py_src tools scripts tests  # 类型检查（strict）
uv run python scripts/spdx.py --check  # SPDX 头门禁
uv run mkdocs serve                # 本地预览文档站
```

提交前顺序：一条命令跑完 `uv run pre-commit run --all-files`（钩子需先装，见
[参与开发](docs/guides/development.md)）。完整说明见 [参与开发](docs/guides/development.md)
与 [怎么改文档](docs/contributing.md#怎么改文档)。

### 打包（Windows）

> ⚠️ **待重做**：旧打包脚本依赖 Qt 时代已删除的层级，下面的命令与 CI 工作流现在都不成立。

```powershell
uv run python scripts/build.py               # 绿色包 -> dist/cairn/
uv run python scripts/build.py --clean       # 先清 build/ 与 dist/
uv run python scripts/build.py --installer   # 再出安装包（需已装 Inno Setup）
```

产物：`dist/cairn/`（免安装 zip）、`dist/installer/Cairn-<ver>-win-x64-setup.exe`；
CI 见 `.github/workflows/build-windows.yml`。

## 平台与分发（规划）

| 平台 / 形态 | 载体 | 优先级 |
|---|---|---|
| 源码 | sdist + wheel | P0 |
| **Windows** 桌面 | 安装包（Inno Setup）+ 免安装 zip | **P0** |
| Linux 服务端 / CLI | 控制台入口 + Docker | P1（待 `src/server` 重设） |
| Linux 桌面 | AppImage | P2 |
| macOS 桌面 | `.dmg` + 公证 | 暂缓 |

## 北极星

可选择性联邦进一个 P2P 博客网络（服务器可选、公私自决、可发现可私网）。网络是增强层，不是本体。

## 许可

Copyright 2026 HanYang06。本项目基于 [Apache License 2.0](LICENSE) 授权，
**禁止引入 GPL / AGPL 依赖**。分发时请一并保留 [`LICENSE`](LICENSE) 与 [`NOTICE`](NOTICE)。
