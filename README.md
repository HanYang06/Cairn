<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Cairn · 巨石堆

> **本地优先的内容寻址对象池** —— 笔记、资产、项目，一台工作台。

一块块往上堆。

```text
文档站     https://hanyang06.github.io/cairn/
仓库       https://github.com/HanYang06/cairn
```

## 定位

- **本地优先**：内容寻址的桶 / 块是本体，应用只是消费者。数据落普通文件
  （`vault/<桶>/packs/*.pack`，定长槽、自框定记录）+ 一个可重建的索引库 `vault/catalog.db`。
  真源是载体，索引库是投影。
- **三件套**：笔记、存储、项目管理。
- **桌面优先**：以 Windows 为主要平台，内核与打包保持跨平台能力。
- **内容寻址对象池**：块按内容哈希去重、身份稳定寻址；**本地落盘明文**，
  加密只用于传输 / 服务端（尚未实现）。这是与其他笔记软件的根本分野。

## 现状

早期开发阶段，**尚未发布**（`0.0.1` / pre-alpha）。

- ✅ 已落地：L0 存储重写完成（块 / 载体 / 桶 / 多桶 / 索引库 / 巡检，内核已接上新底座）、
  类型地基（`Attr` / `Data` / `Cfg`）、配置引擎、信号引擎与内核门户
  （`Core` / `Signal` / `Storage` / `Conf`）、笔记领域（行身份 + 区间样式）、Windows 根壳。
- ⚠️ 已知缺口：**版本能力整体缺失**（随内核重建移除，尚无一处写版本表）；`@action` 动作表未成立；
  `Event` 的网络往返编解码未落。
- 🔜 未做：对象驱动生成、多页 Tab 宿主、笔记编辑页、打包、P2P / 服务端。

**详细进度与取舍不在本文件**——事实源是 [`docs/architecture/`](docs/architecture/index.md) 与代码；
逐篇状态见 [架构文档索引](docs/architecture/index.md)。

## 快速开始

需要 **Python 3.13** 与 [`uv`](https://docs.astral.sh/uv/)：

```powershell
uv sync                 # 安装/同步依赖
uv run pytest           # 跑内核测试（桌面入口尚未就绪）
```

内核不依赖 Qt，可直接用：

```python
from core import Core
from feature import Note

core = Core()  # 内核是单例
core.open("vault")  # 开（不存在则建）一个库
note = Note(core)
data = note.create("第一块石头", title="试笔")
```

完整步骤见 [快速开始](docs/guides/quickstart.md)。
开发库默认 `<repo>/vault/`（已 gitignore），可用 `CAIRN_VAULT` 覆盖；
`CAIRN_DEV_PASSPHRASE`（默认 `cairn-dev`）是 P2P / 服务端到来前的占位。

## 架构

| 目录 | 职责 |
|---|---|
| `py_src/core/` | L0 底座：事件引擎 / 存储引擎 / 配置引擎 / 异常层；**Qt-free、传输无关** |
| `py_src/feature/` | 领域（`note` / `project`）**待重建** |
| `py_src/app/` | Python 侧入口（命令行、未来的内核边车）**待落地** |
| `app/` | 桌面外壳：Tauri 工程（`app/src/` React 前端 · `app/src-tauri/` Rust 壳）**功能待落地** |
| `assets/` | 品牌素材单一真源（logo / 启动图 / Tauri 与安装包图标都从这里取） |

Python 顶层包一律去 `cairn.` 前缀（如 `from core.storage import …`）；源码根叫 `py_src/`
（不叫 `src/`：与 `app/src/` 撞名）。逐层红线见 [`AGENTS.md`](AGENTS.md) 的「架构分层」。

分层红线与约定见 [约定与红线](docs/guides/conventions.md)；设计事实来源见
[架构文档](docs/architecture/index.md)（`storage-design.md` 为 L0 存储的唯一事实来源）。

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
