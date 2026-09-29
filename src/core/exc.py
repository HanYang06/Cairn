# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""内核异常声明。

异常层只做一件事：把"哪一层在什么情况下退出"写成一个类型，调用方按类型分流、
日志按类型定级。此处只声明当前确有抛出点的异常；尚无抛出点的层不得预先占位。
"""

from __future__ import annotations


class CairnError(Exception):
    """内核异常基类：跨层兜底只认这一个。"""


class InvalidIdError(CairnError, ValueError):
    """标识符格式非法：唯一标识凭证或内容摘要凭证不满足各自的形态约束。"""


__all__ = ["CairnError", "InvalidIdError"]
