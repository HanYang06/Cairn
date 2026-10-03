# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""打包入口:先用 PyInstaller 出免安装包,可选再调 Inno Setup 出安装包.

**当前不可运行**:它读的 `packaging/cairn.spec` 以 `src/app` 为入口,而应用层在 2026-09-29 的
内核重建里被整条删除(见 `.agents/skills/memory/progress.md`「界面层重建余项」).
文件留着当参考;UI 外壳回来之后修回,并把 `.github/workflows/build-windows.yml` 的标签触发一并恢复.

用法:
    uv run python scripts/build.py                  # 出 dist/cairn/(onedir 绿色包)
    uv run python scripts/build.py --clean          # 先清掉 build/ 与 dist/
    uv run python scripts/build.py --installer      # 再生成安装包(需已装 Inno Setup)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "cairn.spec"
ISS = ROOT / "packaging" / "windows" / "cairn.iss"
DIST = ROOT / "dist"
WORK = ROOT / "build" / "pyinstaller"
APP_DIR = DIST / "cairn"

_ISCC_CANDIDATES = (
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
)


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return str(tomllib.load(fh)["project"]["version"])


def find_iscc() -> str | None:
    found = shutil.which("iscc") or shutil.which("ISCC")
    if found:
        return found
    for candidate in _ISCC_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    return None


def run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT, env=env)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="打包 Cairn")
    parser.add_argument("--clean", action="store_true", help="先删除 build/ 与 dist/")
    parser.add_argument("--installer", action="store_true", help="再生成 Inno Setup 安装包")
    args = parser.parse_args(argv)

    if args.clean:
        shutil.rmtree(WORK, ignore_errors=True)
        shutil.rmtree(DIST, ignore_errors=True)

    version = project_version()
    env = {**os.environ, "CAIRN_VERSION": version}

    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--distpath",
            str(DIST),
            "--workpath",
            str(WORK),
            str(SPEC),
        ],
        env=env,
    )
    print(f"\n绿色包：{APP_DIR}")

    if not args.installer:
        return 0

    iscc = find_iscc()
    if not iscc:
        print(
            "未找到 ISCC.exe（Inno Setup）。请安装 https://jrsoftware.org/isinfo.php 后重试。",
            file=sys.stderr,
        )
        return 2
    run([iscc, f"/DMyAppVersion={version}", str(ISS)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
