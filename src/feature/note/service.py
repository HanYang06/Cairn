# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""笔记域服务 ``Note``：**管数据**——创建 / 读写 / 落盘 / 版本 / 关系 / 编辑操作。

数据（``NoteData``）只是载体；这边的每个操作都**以 data 为首参**。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.core import Core, Managed
from core.types.event import Intent

from ..shared.asset import AssetData
from ..shared.base import UNSET
from ..shared.canvas import CanvasData
from ..shared.group import GroupData
from ..shared.kinds import Kind
from ..shared.signature import Signature
from .data import NOTE_KIND, NoteData, access_ref, canvas_ref
from .edit import (
    OVERLONG_WEIGHT,
    apply_text,
    clear_range_style,
    coerce_style,
    drop_style,
    insert_line,
    is_marker,
    line_styles,
    merge_line,
    merge_style,
    new_id,
    normalize_body,
    remove_line,
    set_line_text,
    set_range_style,
    split_line,
    split_style,
    text_weight,
    toggle_range_style,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence


class Note(Managed):
    """笔记域服务：创建 / 读写 / 落盘 / 关系 / 编辑操作。

    它是**受内核管辖的对象**（继承 `Managed` 即登记）；落盘经内核 `self.core.put(data)`。
    版本**不在这里**：作者定「版本由各领域日后自建」，故本服务只做落盘，不留版本链。
    """

    type = Kind.Feature.Note
    name = "note"  # 内核表里的名字
    data = (NoteData, AssetData, CanvasData, GroupData)  # 本域用到的数据类（body 免列）
    light = [NoteData]  # noqa: RUF012 — 最小数据单元（可多个）

    def __init__(self, core: Core) -> None:
        super().__init__(core)  # 接内核：登记实例 + 记住内核

    # ---- 创建 / 读取 ----
    def create(
        self,
        text: str = "",
        *,
        title: str | None = None,
        tags: Iterable[str] | Mapping[str, Any] | None = None,
        props: dict[str, Any] | None = None,
    ) -> NoteData:
        """新建一条笔记：落盘，返回其数据。"""
        data = NoteData()
        data.core = self.core  # 数据对象身上带内核（它继承 Block，不继承 Managed）
        self.set_text(data, text)
        data.title = title
        data.tags = tags or {}
        if props:
            data.attrs["props"] = dict(props)
        # 创作签名：锁在创建时的正文内容上（原始结构据此可找回；剥离行 id）
        subject = data.body.refresh().hash
        data.signature = Signature.create(author=data.author or "", subject=subject)
        self.save(data)
        return data

    def load(self, oid: str) -> NoteData:
        """按 oid 载入一条笔记数据（经内核）。"""
        data: NoteData = self.core.get(NoteData, str(oid))
        data.core = self.core
        return data

    def list_notes(
        self,
        *,
        tags: Iterable[str] | Mapping[str, Any] | None = None,
    ) -> list[NoteData]:
        """列出笔记数据；``tags`` 给出时按标签筛选（口径同 `Core.iter`）。

        先取中立视图按类型过滤，再按命中的 id 解码：库里的资产 / 画板 / 分组 / 关系
        都不是笔记，直接对每个 id 调 ``get(NoteData, ...)`` 会在第一个非笔记块上抛错中断。
        """
        return [self.load(info.oid) for info in self.core.iter(type=NOTE_KIND, tags=tags)]

    # ---- 正文操作（编辑器接线用；只改内存，落盘由 save / persist 负责）----
    def set_text(self, data: NoteData, text: str) -> None:
        """整段替换文字；行 id 与嵌入占位尽量保留。"""
        data.body.text = apply_text(data.body.text, text)
        data.body.refresh()

    def set_body(
        self,
        data: NoteData,
        lines: Sequence[Mapping[str, Any]],
        *,
        style: Mapping[str, Any] | None = None,
    ) -> NoteData:
        """整段替换正文（编辑器回写用）：行序列 + 可选行内样式。"""
        data.body.text = normalize_body(lines)
        if style is not None:
            data.body.style = coerce_style(style, data.body.text)
        data.body.refresh()
        return data

    def blocks(self, data: NoteData) -> list[dict[str, Any]]:
        """给界面用的块视图：行 + 行内样式段 + 段落属性 + 等效字数。"""
        blocks: list[dict[str, Any]] = []
        for line in data.body.text:
            value = line["v"]
            para = dict(line.get("p") or {})
            if is_marker(value):
                kind = "canvas" if "canvas" in value else "access"
                blocks.append(
                    {
                        "id": line["id"],
                        "kind": kind,
                        "text": "",
                        "styles": [],
                        "index": int(value.get(kind, 0)),
                        "para": para,
                        "weight": 0.0,
                    }
                )
                continue
            styles = [
                [start, end, style.to_data()] for start, end, style in line_styles(data.style, line)
            ]
            weight = text_weight(str(value))
            blocks.append(
                {
                    "id": line["id"],
                    "kind": "text",
                    "text": value,
                    "styles": styles,
                    "index": -1,
                    "para": para,
                    "weight": weight,
                    "overlong": weight > OVERLONG_WEIGHT,
                }
            )
        return blocks

    def reorder(self, data: NoteData, order: Sequence[int]) -> None:
        """按旧下标顺序重排行；样式按行 id 自动跟随。``order`` 须是完整排列。"""
        lines = list(data.body.text)
        if sorted(order) != list(range(len(lines))):
            raise ValueError(f"order 必须是 0..{len(lines) - 1} 的完整排列: {list(order)}")
        data.body.text = [lines[index] for index in order]
        data.body.refresh()

    def set_line(self, data: NoteData, line_id: str, text: str) -> NoteData:
        """改写某一行文字（含换行时就地拆行）。"""
        data.body.text = set_line_text(data.body.text, line_id, text)
        data.body.refresh()
        return data

    def insert_line_after(self, data: NoteData, line_id: str | None, text: str = "") -> str:
        """在某行之后插入一行（``None`` 追加末尾），返回新行 id。"""
        data.body.text, new_lid = insert_line(data.body.text, line_id, text)
        data.body.refresh()
        return new_lid

    def remove_line(self, data: NoteData, line_id: str) -> NoteData:
        """删除一行；其样式一并丢弃。"""
        data.body.text = remove_line(data.body.text, line_id)
        data.body.style = drop_style(data.body.style, line_id)
        data.body.refresh()
        return data

    def split_line(self, data: NoteData, line_id: str, offset: int) -> str:
        """在某行 ``offset`` 处拆行；样式按位置切开。返回新行 id（无可拆目标返回原 id）。"""
        target = next(
            (line for line in data.body.text if line["id"] == line_id and not is_marker(line["v"])),
            None,
        )
        if target is None:
            return line_id
        data.body.text, new_lid, _, _ = split_line(data.body.text, line_id, offset)
        data.body.style = split_style(data.body.style, line_id, new_lid, int(offset))
        data.body.refresh()
        return new_lid

    def merge_line(self, data: NoteData, line_id: str) -> str | None:
        """把某行并入上一行（上一行文字在前）；首行或涉及占位时不合并。

        返回合并后的行 id（未合并返回 ``None``）。调用方可据此把光标移回去。
        """
        lines, prev_id, prev_len = merge_line(data.body.text, line_id)
        if prev_id is None:
            return None
        data.body.text = lines
        data.body.style = merge_style(data.body.style, prev_id, line_id, prev_len)
        data.body.refresh()
        return prev_id

    def toggle_style(
        self, data: NoteData, line_id: str, start: int, end: int, key: str
    ) -> NoteData:
        """对某行 ``[start, end)`` 切换布尔样式（bold / italic / underline / strike）。"""
        toggled = toggle_range_style(data.body.style, line_id, start, end, key)
        data.body.style = coerce_style(toggled, data.body.text)
        data.body.refresh()
        return data

    def set_style_span(
        self,
        data: NoteData,
        line_id: str,
        start: int,
        end: int,
        patch: Mapping[str, Any],
    ) -> NoteData:
        """对某行 ``[start, end)`` 设置若干行内样式字段（颜色 / 字号 / 字体 / 布尔）。"""
        changed = set_range_style(data.body.style, line_id, start, end, patch)
        data.body.style = coerce_style(changed, data.body.text)
        data.body.refresh()
        return data

    def clear_style_span(self, data: NoteData, line_id: str, start: int, end: int) -> NoteData:
        """清掉某行 ``[start, end)`` 的全部行内样式。"""
        changed = clear_range_style(data.body.style, line_id, start, end)
        data.body.style = coerce_style(changed, data.body.text)
        data.body.refresh()
        return data

    # ---- 段落属性（行级；一行 = 一段）----
    def set_paragraph(self, data: NoteData, line_id: str, patch: Mapping[str, Any]) -> NoteData:
        """合并段落属性；值为 ``None`` / 空串 / 空列表则删除该键。"""
        for line in data.body.text:
            if line["id"] != line_id:
                continue
            para = dict(line.get("p") or {})
            for key, value in patch.items():
                if value in (None, "", [], {}):
                    para.pop(key, None)
                else:
                    para[key] = value
            if para:
                line["p"] = para
            else:
                line.pop("p", None)
            break
        data.body.refresh()
        return data

    def clear_paragraph(self, data: NoteData, line_id: str) -> NoteData:
        """清掉某行的全部段落属性。"""
        return self.set_paragraph(data, line_id, dict.fromkeys(data.paragraph(line_id)))

    # ---- 落盘 ----
    def save(self, data: NoteData) -> NoteData:
        """**落盘 + 广播**：写进去，并让订阅方知道这条笔记变了。版本由领域日后自建。"""
        self.core.put(data)
        self.notify(data)
        return data

    def persist(self, data: NoteData) -> NoteData:
        """**只落盘**：连续编辑的自动保存走这里，不广播（与 `save` 的差别仅此一处）。"""
        self.core.put(data)
        return data

    def notify(self, data: NoteData) -> None:
        """把"这条笔记变了"作为**事件**发出去（不带动作 = 广播，谁关心谁听）。

        事件带上变更对象的 oid（``Event.target``）：订阅方据此定位是哪条笔记，
        否则只能收到一次无主体的 PUT 广播。
        """
        self.core.send(Intent.PUT, target=str(data.oid))

    # ---- 属性 / 关系 / 嵌入 ----
    def update(
        self,
        data: NoteData,
        *,
        text: str | None = None,
        title: str | None = UNSET,
        tags: Iterable[str] | Mapping[str, Any] | None = None,
        props: dict[str, Any] | None = None,
    ) -> NoteData:
        """更新属性 / 正文并落盘记版本。"""
        merged = data.props()
        if props:
            merged.update(props)
        if title is not UNSET:
            data.title = title
        if tags is not None:
            data.tags = tags
        data.attrs["props"] = merged
        if text is not None:
            self.set_text(data, text)
        self.save(data)
        return data

    def link(self, data: NoteData, target: str, relation: str = "references") -> Any:
        """从本笔记向目标建一条关系。"""
        from ..shared.relation import Relation  # noqa: PLC0415 — 延迟导入，避免领域间加载期环

        return Relation.create(self.core, data.oid, target, relation=relation, domain="note")

    def add_canvas(self, data: NoteData, canvas: CanvasData) -> str:
        """把一块画板嵌进正文：``canvas`` 追加其 oid，并在 body 末尾放占位。"""
        entry = str(canvas.oid)
        data.canvas = [*data.canvas, entry]
        self._append_marker(data, canvas_ref(len(data.canvas) - 1))
        self.save(data)
        return entry

    def add_access(
        self,
        data: NoteData,
        oid: str,
        *,
        mime: str = "",
        name: str = "",
        size: float = 0.0,
    ) -> str:
        """把一段外联资源嵌进正文：``access`` 追加 asset 的 oid，body 末尾放占位。

        资源本体与其元数据都在 ``Asset`` 块里，这里只存引用。
        """
        del mime, name, size
        entry = str(oid)
        data.access = [*data.access, entry]
        self._append_marker(data, access_ref(len(data.access) - 1))
        self.save(data)
        return entry

    def _append_marker(self, data: NoteData, marker: dict[str, int]) -> None:
        data.body.text = [*data.body.text, {"id": new_id(), "v": marker}]
        data.body.refresh()


__all__ = ["Note"]
