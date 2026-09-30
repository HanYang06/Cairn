<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 快速开始

!!! warning "先说结论：还没有能用的界面"

    Cairn **尚未发布**。桌面入口（`uv run cairn` / `python -m app`）在 Windows 上已有根壳，
    但功能远未齐备；旧 PySide6 界面整体移除后正在重建。
    **现在能跑的是内核与测试**，下面的第二段才是真正可用的部分。

## 1. 准备环境

需要 **Python 3.13** 与 [`uv`](https://docs.astral.sh/uv/)：

```powershell
git clone https://github.com/HanYang06/cairn.git
cd cairn
uv sync                 # 建立 .venv 并装齐依赖（含 PySide6、开发工具）
```

## 2. 跑内核（当前唯一稳的用法）

内核**不依赖 Qt**，可以直接用：

```powershell
uv run python
```

```python
from core import Core
from feature import Note

core = Core()  # 内核是单例：拿到它就拿到全部
core.open("vault")  # 开（不存在则建）一个库；默认路径是 <cwd>/vault

note = Note(core)  # 领域服务（受内核管辖；已存在则复用）
data = note.create("第一块石头", title="试笔")
print(data.id, data.type)  # 稳定 OID + 类型名

again = core.get(type(data), data.id)  # 按 OID 取回（经存储还原真实类型）
print(again.title)

core.close()
```

要点：

- **落盘一律显式 `core.put(data)`**；领域服务内部代为实现，调用方不得直接写文件。
- **库就是目录**：`<root>/catalog.db`（索引库，可重建的投影）+ `<root>/<hub>/packs/*.pack`（载体，真源）。
  索引丢了能顺扫载体重建（`rows.rebuild`），巡检与处置是库级动作（`patrol` / `repair`，
  从 `Kernel.patrol()` / `Kernel.repair()` 进）。
- **本地不加密**，明文落盘；加密只用于传输 / 服务端（当前未实现）。

## 3. 跑测试

测试不需要任何外部服务，全部使用临时本地库：

```powershell
uv run pytest                                        # 全部（含覆盖率）
uv run pytest tests/core/test_vault.py -x            # 单个文件
uv run pytest -k "conf" -x                           # 按名字筛
```

## 4. 起桌面壳（实验性）

```powershell
uv run python -m app
```

- 库根取 `CAIRN_VAULT` 环境变量，空白或未设时用 `<当前目录>/vault`。
- `CAIRN_THEME_DIR` / `CAIRN_SHAPES` 可覆盖主题目录与图形集（默认为仓库内的 `config/`）。
- 非 Windows 平台**没有 UI**：`python -m app` 会打印提示并返回退出码 2（不假装能用）。

## 5. 下一步

- 想改代码 → 「[参与开发](development.md)」与「[约定与红线](conventions.md)」
- 想看设计 → 「[架构](../architecture/index.md)」
- 想查某个类 / 函数的准确签名 → 「[API 参考](../api/index.md)」
