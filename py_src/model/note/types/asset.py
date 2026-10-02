# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""资产：媒体的载体。

**没有"是否分片"这个字段**：默认就是分片、必然分片，故那个开关没有存在的理由。
**分片粒度尚未定**：它是领域策略，而"把本体切成片"的那一层（``model/note/format/``）
与它的配置项都还没落地，故这里不写一个假的口径。

元数据是**跟着块走的小字段**（资源类型 / 字节数 / 分辨率 / 时长 / 时间基），
本体不进属性：它是载荷，也就是**分片清单**。片块各自是普通的块，故"只读一部分"
就是按清单逐个取。
"""

from __future__ import annotations

from dataclasses import dataclass

from core.storage.engine import Block
from core.storage.types import Attr, Body

__all__ = ["Chunk", "NoteAsset"]


@dataclass(slots=True)
class Chunk:
    """一片：片块的 ID，以及它有多少字节。

    顺序即拼回来的顺序，故清单是个列表、不排序。它是**载荷里的结构**，
    不建表，随载荷一起重建。
    """

    id: str = ""
    size: int = 0


class NoteAsset(Block):
    """一份媒体。

    表名只由类名算出来（``NoteAsset`` → ``noteasset``）：资产是**笔记领域专属**的，
    ``project`` 那边可以做出同名概念而互不相干，两边不互相引用。

    本类不写 ``__init__``：基座那一支收下身份，不给就现签一个。
    """

    mime: str = Attr("")  # type: ignore[assignment]
    size: int = Attr(0)  # type: ignore[assignment]
    width: int = Attr(0)  # type: ignore[assignment]
    height: int = Attr(0)  # type: ignore[assignment]
    duration: int = Attr(0)  # type: ignore[assignment]
    timescale: int = Attr(1)  # type: ignore[assignment]
    original: str = Attr("")  # type: ignore[assignment]
    chunks: list[Chunk] = Body([])  # type: ignore[assignment]

    def total_bytes(self) -> int:
        """本体一共多少字节（由清单算出来，不另存一份）。

        ``size`` 那份是"不读载荷就知道大小"的缓存；两者若分叉，以清单为准。
        """
        return sum(chunk.size for chunk in self.chunks)
