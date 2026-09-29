# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""把配置声明展开成两个投影：``config/<包树>/…`` 与 ``schema/<包树>/…``。

**当前不可运行**：它 import 的 `core.conf` / `core.storage.conf` 在 2026-09-29 的内核重建里
被整条删除，配置引擎正由作者在新结构下重做（`src/core/conf/`）。文件留着当参考，
配置引擎落地后按新接口修回；`pyproject.toml` 的 mypy 覆盖里为它开了豁免，修回时请一并摘掉。

跑法（提交新声明后跑一次，和 `tools/spdx.py` 一样是工程工具）::

    uv run python tools/gen_conf.py            # 展开 / 补齐
    uv run python tools/gen_conf.py --write    # 同上（写盘意图显式化）
    uv run python tools/gen_conf.py --check    # 只查不写（CI 防漂移）

未知参数一律报错退出：拼错成 `-check` 之类的写法若被当成"默认展开"，
会在意图是"只看一眼"的时候写盘。**声明是唯一事实来源**：这个工具不发明任何值，只把声明展开到磁盘。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if str(ROOT) not in sys.path:  # 直接跑脚本时，`tools` 未必在导入路径上
    sys.path.insert(0, str(ROOT))

# 导入即登记：**每加一个带配置的模块，在这里补一行**（声明写在各模块自己的 params.py 里）。
import core.conf.params  # noqa: E402
import core.storage.conf  # noqa: E402,F401
from core.conf import ConfEngine  # noqa: E402
from tools._iosafe import _say  # noqa: E402 — 仓根在 sys.path[0] 后即可导入


def main(argv: list[str]) -> int:
    unknown = [arg for arg in argv if arg not in {"--check", "--write"}]
    if unknown:
        _say(f"未知参数 {unknown}：用法 `gen_conf.py [--check|--write]`（不带参数=展开 / 补齐）")
        return 1
    check = "--check" in argv
    engine = ConfEngine(ROOT)
    plans = engine.plan()
    if not plans:
        _say("没有任何配置声明：检查上面的 import 清单是否漏了模块")
        return 1
    clashes = engine.conflicts(plans)
    if clashes:
        for line in clashes:
            _say(f"重名 {line}")
        _say("目标路径上压着不是本引擎写的文件：**拒写**——请搬迁或换 hub（CONFIG_HUB）")
        return 1
    stale = [path for path, _payload, outdated in plans if outdated]
    if check:
        if stale:
            for path in stale:
                _say(f"漂移 {path.relative_to(ROOT)}")
            _say("配置投影与声明不一致：请跑 uv run python tools/gen_conf.py")
            return 1
        _say("配置投影与声明一致")
        return 0
    touched = engine.sync()
    for path, written in touched:
        if written:
            _say(f"写入 {path.relative_to(ROOT)}")
    _say(f"共 {len(touched)} 份投影，{len(stale)} 份有变更")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
