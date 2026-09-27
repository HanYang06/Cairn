# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""笔记**数据描述**：值类型 + 内容容器 + 载体。

- `NoteBody`：正文容器（行序列 + 行内样式，自带内容哈希）。
- `NoteData`：数据块（载体）——正文 + 画板 / 资源引用 + 属性；**不含操作**（操作在 `service.py`）。
- 值类型 `Style` 在 `edit/style.py`（样式逻辑的家）；这里只转出画板值类型（`Graphic` 等）。

样式区间见 `edit/`；行 id 生成即锁死，内容签名剥离行 id。
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, ClassVar

from blake3 import blake3

from core.storage import Block, Body, canonical
from core.types import InvalidIdError, ValueUuid
from core.types.attr import Attr

from ..shared.base import normalize_tags
from ..shared.canvas import CanvasBody, CanvasData, Form, Graphic, Line, Link, Paint
from ..shared.kinds import Kind
from ..shared.signature import Signature
from .edit import (
    Line as LineDict,
)
from .edit import (
    StyleMap,
    coerce_style,
    encode_style,
    flatten_text,
    normalize_body,
    signature_style,
)

NOTE_KIND = Kind.Data.Notedata
NOTE_MIME = "application/x-cairn-note"
NOTE_SCHEMA = 1

Text = str
Segment = Text | dict[str, Any]


class NoteBody(Body):
    """正文容器：``text``（行序列）+ ``style``（行内样式）；自带状态 ``hash``。

    - 行为像 list（迭代 / 下标 / 长度代理到 ``text`` 的行），方便 ``note.body[0]["v"]``。
    - ``hash`` = 对 ``content()``（行值 + 行内样式，**剥离行 id**）求摘要；
      不含 attrs / 签名 / 时间戳。内容一变就 ``refresh()`` 重算并存起来。
    """

    def __init__(self, text: Any = None, style: Any = None, hash: str = "") -> None:
        self.text: list[LineDict] = normalize_body(text)
        self.style: StyleMap = coerce_style(style, self.text)
        self.hash = str(hash or "")
        if not self.hash:
            self.refresh()

    def content(self) -> dict[str, Any]:
        return {
            "text": [line["v"] for line in self.text],
            "para": [line.get("p") or {} for line in self.text],
            "style": signature_style(self.text, self.style),
        }

    def to_data(self) -> dict[str, Any]:
        return {"text": self.text, "style": encode_style(self.style), "hash": self.hash}

    @classmethod
    def from_data(cls, data: Any) -> NoteBody:
        if not data:
            return cls()
        if isinstance(data, Mapping) and "text" in data:
            return cls(
                text=data.get("text"),
                style=data.get("style"),
                hash=str(data.get("hash") or ""),
            )
        return cls(text=data)  # 兼容：旧 body 就是裸行序列

    @property
    def plain(self) -> str:
        return flatten_text(self.text)

    def refresh(self) -> NoteBody:
        super().refresh()
        return self

    def __iter__(self) -> Any:
        return iter(self.text)

    def __getitem__(self, index: Any) -> Any:
        return self.text[index]

    def __len__(self) -> int:
        return len(self.text)


def canvas_ref(index: int) -> dict[str, int]:
    """正文里的画板占位：指向 ``canvas`` 列表的第 ``index`` 块。"""
    return {"canvas": index}


def access_ref(index: int) -> dict[str, int]:
    """正文里的多媒体占位：指向 ``access`` 列表的第 ``index`` 项。"""
    return {"access": index}


class NoteData(Block):
    """笔记数据块：正文容器 + 画板 + 多媒体 + 属性（纯数据）。"""

    type = NOTE_KIND
    mime: ClassVar[str | None] = NOTE_MIME

    body: NoteBody = NoteBody()
    canvas: list[str] = []  # noqa: RUF012  # 画板：存 Canvas 的 oid（全局去重）
    access: list[str] = []  # noqa: RUF012  # 外联资源：存 Asset 的 oid（全局去重）

    # 属性（正文之外，全在这里）：注解即类型，右边即默认值
    schema: Attr[int] = NOTE_SCHEMA
    title: Attr[str | None] = None
    tags: Attr = Attr(factory=dict, coerce=normalize_tags)  # coerce → 显式
    authors: Attr[list[Any]] = []  # noqa: RUF012
    signature: Attr[Signature] = Signature()
    privacy: Attr[str] = ""
    favorite: Attr[bool] = False
    archived: Attr[bool] = False
    trashed: Attr[bool] = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # 上次落盘基线；域服务 ``save()`` 据此记版本检查点
        self._saved_state: dict[str, Any] | None = None

    # ---- 去重键 = 落盘负载的哈希 ----
    def body_hash(self) -> str:
        """内容池去重键 = **落盘负载的哈希**。

        负载（``to_data``）里含行 id，故去重键必须与负载口径一致，否则不同行 id
        的笔记会命中同一内容行、读回时被静默替换成别人的行 id。供签名 / 版本用的
        「剥离行 id」的内容签名是 ``self.body.hash``，二者分工不同。
        """
        self.body.refresh()
        return blake3(canonical(self.body.to_data())).hexdigest()

    # ---- 正文读视图 ----
    @property
    def text(self) -> str:
        return self.body.plain

    @property
    def style(self) -> StyleMap:
        return self.body.style

    @style.setter
    def style(self, value: Any) -> None:
        self.body.style = coerce_style(value, self.body.text)
        self.body.refresh()

    def paragraph(self, line_id: str) -> dict[str, Any]:
        """取某行的段落属性。"""
        for line in self.body.text:
            if line["id"] == line_id:
                return dict(line.get("p") or {})
        return {}

    @property
    def references(self) -> tuple[str, ...]:
        """正文里引用到的外联资源（``access`` 里的 asset oid）；跳过解析失败的脏值。"""
        refs: list[str] = []
        for oid in self.access:
            if not oid:
                continue
            try:
                refs.append(str(ValueUuid.parse(str(oid))))
            except InvalidIdError:
                continue
        return tuple(refs)

    # ---- 版本状态（域服务用）----
    def _state(self) -> dict[str, Any]:
        return {
            "body": [
                {
                    "id": line["id"],
                    "v": copy.deepcopy(line["v"]),
                    **({"p": copy.deepcopy(line["p"])} if line.get("p") else {}),
                }
                for line in self.body.text
            ],
            "style": encode_style(self.body.style),
        }


__all__ = [
    "NOTE_KIND",
    "NOTE_MIME",
    "NOTE_SCHEMA",
    "CanvasBody",
    "CanvasData",
    "Form",
    "Graphic",
    "Line",
    "Link",
    "NoteBody",
    "NoteData",
    "Paint",
    "Segment",
    "Text",
    "access_ref",
    "canvas_ref",
]
