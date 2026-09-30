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
from core.storage.format.block import Block

__all__ = ["Chunk", "NoteAsset", "NoteAssetBody"]


@dataclass(frozen=True, slots=True)
class Chunk:
    """一片：片块的 ID，以及它有多少字节。

    顺序即拼回来的顺序，故不排序。
    """

    id: str = ""
    size: int = 0


@dataclass(frozen=True, slots=True)
class NoteAssetBody:
    """资产的载荷：分片清单。

    一份媒体一个容器、整份塞二进制、存时切片（作者口径），故载荷就是这张清单。
    """

    chunks: tuple[Chunk, ...] = ()

    @property
    def size(self) -> int:
        """本体一共多少字节（由清单算出来，不另存一份）。"""
        return sum(chunk.size for chunk in self.chunks)

    def __len__(self) -> int:
        """切成了几片。"""
        return len(self.chunks)


@dataclass(slots=True)
class NoteAsset(Block[NoteAssetBody]):
    """一份媒体。

    ``__table__`` 带 ``note`` 前缀：资产是**笔记领域专属**的，``project`` 那边
    可以做出同名概念而互不相干，两边不互相引用。
    """

    __table__ = "noteasset"
    __owner__ = "note"

    mime: attr[str] = ""
    """资源类型。**渲染策略由它现算**，不落成并列的类型：三个枚举装不下
    gif / webp / svg / pdf / 字幕 / 波形这一串。"""

    size: attr[int] = 0
    """本体的字节数。

    它与载荷里那份清单能算出来的总数是同一个数——这里存一份是为了**不读载荷就知道大小**
    （列表与配额判断都要用）。两者若分叉，以载荷为准。
    """

    width: attr[int] = 0
    """像素宽；不是图（或不知道）时为 0。"""

    height: attr[int] = 0
    """像素高；同上。"""

    duration: attr[int] = 0
    """时长为多少个时间基单位；不是时序媒体时为 0。"""

    timescale: attr[int] = 1
    """时间基：一个时间单位等于多少分之一秒。"""

    original: attr[str] = ""
    """原始文件名，纯为显示与下载命名用；它**不是身份**。"""
