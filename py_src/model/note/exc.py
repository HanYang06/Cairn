# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""笔记侧的异常.

与 `core.exc` 的分工:那边是内核那一族(存储 / 配置 / 命令面),这边是**领域输入非法**.
两条规矩照抄内核:① 只声明确有抛出点的类型,尚无抛出点的层不预先占位;
② 基类同时继承 `ValueError`,调用方既能按 `CairnError` 兜住整层,也能像普通参数错误那样就地捕获.

命名里的"笔记"是这一族的**第一个域**,不是全部:将来出现第二个域时,基类上提到
`model/shared/`,此处只留笔记专有的那几条(判据照旧:第二个调用方出现才抽).
"""

from __future__ import annotations

from core.exc import CairnError

__all__ = ["LineShapeError", "NoteError", "SpanRangeError"]


class NoteError(CairnError, ValueError):
    """笔记侧一切非法输入的基类."""


class LineShapeError(NoteError):
    """行的载荷与行类型对不上:`data` 不是这个 `kind` 该有的形态.

    判别联合不能破:读 `data` 之前要先按 `kind` 分支,所以两者必须始终配套.
    """


class SpanRangeError(NoteError):
    """行内区间非法:起点为负,或终点早于起点."""
