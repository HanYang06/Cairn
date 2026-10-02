<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 快速开始

!!! warning "当前没有可用的界面"

    Cairn **尚未发布**。桌面壳（Tauri + Web 前端，`app/`）已立项，边车与转发口已接线，
    但功能远未齐备。**内核此刻亦不成立**：L0 存储正在重写，`core.init` 依赖的存储模块尚未
    补齐，故下面第 2 节的示例与第 3 节的测试都要等这次重写落地。

## 1. 准备环境

需要 **Python 3.13** 与 [`uv`](https://docs.astral.sh/uv/)：

```powershell
git clone https://github.com/HanYang06/cairn.git
cd cairn
uv sync                 # 建立 .venv 并装齐依赖（不含任何 Qt 组件）
```

## 2. 运行内核

内核不依赖 Qt，可直接调用。库根由调用方显式给出，示例：

```python
from core.init import Kernel

with Kernel.create("vault") as kernel:            # 建库并装配；已有库改用 Kernel.open
    ident = kernel.store(b"第一块石头", kind="note")   # 存入 body，返回块身份 ID
    print(ident.value_uuid, ident.value_hash)     # uuid4 比较有效 / sha256 去重有效

    data = kernel.load(ident.value_uuid)          # 按身份读回
    print(data)
```

要点：

- **落盘一律经 `kernel.store(data)`**；领域服务（待重建）内部代为实现，调用方不直接写文件。
- **库就是目录**：`<root>/catalog.db`（索引库，可重建的投影）＋ `<root>/<hub>/packs/*.pack`
  （载体，真源）。索引丢失可顺扫载体重建；巡检与处置是库级动作
  （`kernel.patrol()` 只报告，`kernel.repair(report)` 只补不删）。
- **本地不加密**，明文落盘；加密只用于传输 / 服务端（设计篇 §9.5，当前未实现）。

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
- 想看设计 → 「[配置引擎](../architecture/py_core/config.md)」；`docs/architecture/**` 其余各页待重写
- 想查某个类 / 函数的准确签名 → 「[API 参考](../api/index.md)」
