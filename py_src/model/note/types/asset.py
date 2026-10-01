# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""资产：媒体的载体。

**没有"是否分片"这个字段**：默认就是分片、必然分片，故那个开关没有存在的理由。
分片粒度由配置判——`core/storage/conf.py` 的 `storage.block.max_bytes` 本来就写着
"单个块的字节上限，超过即分片"，它就是这里说的那个"最小尺寸"。

元数据是**跟着块走的小字段**（资源类型 / 字节数 / 分辨率 / 时长 / 时间基），
本体不进属性：它是载荷，也就是**分片清单**。片块各自是普通的块，故"只读一部分"
就是按清单逐个取。
"""

from __future__ import annotations

from dataclasses import dataclass

from core.attr import attr
from core.storage.format.block import Block, Body
from core.storage.format.id import ID

__all__ = ["Chunk", "NoteAsset"]


@dataclass(slots=True)
class Chunk:
    """一片：片块的 ID，以及它有多少字节。

    顺序即拼回来的顺序，故清单是个列表、不排序。它是**载荷里的结构**，
    不登记、不建表，随载荷一起重建。
    """

    id: str = ""
    size: int = 0


class NoteAsset(Block):
    """一份媒体。

    ``__table__`` 带 ``note`` 前缀是默认值（类名小写）：资产是**笔记领域专属**的，
    ``project`` 那边可以做出同名概念而互不相干，两边不互相引用。
    """

    def __init__(self) -> None:
        """声明字段。本体（分片清单）是载荷，其余是属性。"""
        super().__init__()
        self.id = ID()
        self.mime = attr(default="")
        self.size = attr(default=0)
        self.width = attr(default=0)
        self.height = attr(default=0)
        self.duration = attr(default=0)
        self.timescale = attr(default=1)
        self.original = attr(default="")
        self.chunks = Body(factory=list[Chunk])

    def total_bytes(self) -> int:
        """本体一共多少字节（由清单算出来，不另存一份）。

        ``size`` 那份是"不读载荷就知道大小"的缓存；两者若分叉，以清单为准。
        """
        return sum(chunk.size for chunk in self.chunks)
