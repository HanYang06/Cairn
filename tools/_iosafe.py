# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""控制台输出的编码兜底(开发工具共用,不参与产品).

Windows 上 Python 按**活动代码页**编码 stdout,中文会抛
``UnicodeEncodeError: charmap`` 而让 CI 作业失败——本地 UTF-8 终端看不出来.
凡是要打印中文的工具,一律走这里的 :func:`_say`.
"""

from __future__ import annotations

import sys


def _say(message: str) -> None:
    """打印一行(可含多行):统一以 UTF-8 写 ``stdout``(拿不到 buffer 时退回 ``print``)."""
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        print(message)
        return
    stream.write((message + "\n").encode("utf-8"))
    stream.flush()


__all__ = ["_say"]
