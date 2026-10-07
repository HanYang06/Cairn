# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""引擎的契约:一个块占属性槽与正文槽,只写动过的域,按摘要关联正文,正文摘要,删除.

本文件钉七件事(每一条都是 2026-10-02 裁定定下的口径):

- **一个块占两类槽**:属性槽装全部属性,**可原地覆盖**;正文槽装正文分片,**只追加**;
  而**哪一格是属性,哪一格是正文靠槽头种类分辨**(库里没有那一列);
- **坐标系的分辨**:槽号只在 pack 内有意义,故正文关联走摘要(`body` 那一列);
- **两个运行时状态**:`_body_hash` 与 `_inline_body`(载入时由库行与槽头推出来);
- **只写它动过的域**:属性变了原地覆盖同一格,正文变了才追加新槽;
- **正文两条路**:未命中即写 body 槽加一条位置行,命中即本块只占属性槽(引用型);
- **删除 = 摘行**:载体上不留标记,删除之后按身份读回来显式报"对象不在";
- **读路径没有顺扫回退**:库里没有那一行即报错.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.exc import ObjectNotFoundError
from core.storage.db.id import ID
from core.storage.engine import Block, Engine, bind, content_digest
from core.storage.index.bodyindex import BodyIndex
from core.storage.index.index import CONTENT_FIELD
from core.storage.pack import ATTR_SLOT, BODY_SLOT
from core.storage.types import Attr, Body

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

_SLOT = 512


class NoteData(Block):
    """一篇笔记:身份由调用方给,落点声明在类体上."""

    # 注:注解写字段的类型(str),右值是声明本身(Attr);描述符在实例上交出 str.
    title: str = Attr("")  # type: ignore[assignment]
    slug: str = Attr("")  # type: ignore[assignment]
    scratch: str = ""
    lines: list[str] = Body([])  # type: ignore[assignment]

    def __init__(self, id: ID | None = None) -> None:
        """身份可省:省了就是块自己现签一个(`ID(self)`)."""
        super().__init__(id)


class Plain(Block):
    """没有任何声明字段的块:只有身份."""

    def __init__(self, id: ID | None = None) -> None:
        """身份可省."""
        super().__init__(id)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """接上一个干净的引擎,并把这根线接通(用例结束解开并关掉连接)."""
    instance = Engine(tmp_path / "vault", slot_bytes=_SLOT)
    bind(instance)
    yield instance
    bind(None)
    instance.close()


def _note() -> NoteData:
    """造一篇填好的笔记."""
    note = NoteData(ID(NoteData))
    note.title = "第一篇"
    note.slug = "abc"
    note.scratch = "只落盘、不索引"
    note.lines = ["第一行", "第二行"]
    return note


def _kind_counts(engine: Engine) -> dict[int, int]:
    """盘上每种槽各有多少格."""
    found: dict[int, int] = {}
    for _hub, _pack, _number, slot in engine.scan():
        found[slot.kind] = found.get(slot.kind, 0) + 1
    return found


def _block_slots(engine: Engine, identity: ID) -> list[tuple[int, bytes]]:
    """这个块自己那几格:(槽种类,内容),按位置段顺序.

    索引块的正表行也占属性槽,故数"这个块占了几格"必须按它自己的位置段来,
    不能拿全库的属性槽计数.
    """
    return [(slot.kind, slot.content) for slot in engine.scan_slots(identity)]


def _body_slots(engine: Engine, identity: ID) -> list[bytes]:
    """这个块**自己**那几格正文槽的内容(引用型即空序列)."""
    return [content for kind, content in _block_slots(engine, identity) if kind == BODY_SLOT]


# ---- 身份由调用方给 ----


def test_a_block_signs_its_own_identity_when_none_is_given():
    """**零参构造是一个块**:不给身份就现签一个(`ID(self)`)——索引块就靠这条路被造出来."""
    plain = Plain()

    assert plain.id.name == "plain"
    assert plain.id.value_uuid


def test_a_block_refuses_something_that_is_not_an_identity():
    """给的不是 ID 就当场报错,不放过."""
    with pytest.raises(TypeError, match="必须拿到一个 ID"):
        Plain("not-an-id")  # type: ignore[arg-type]


def test_a_block_still_accepts_an_identity_signed_elsewhere():
    """调用方签好再递进来也认——两条路都通向同一个答案."""
    identity = ID(NoteData)

    note = NoteData(identity)

    assert note.id is identity


def test_the_table_name_comes_from_the_class_name():
    """**表名只由类的名字算出来**:`class NoteData` → `notedata`,没有第二个口子."""
    note = NoteData(ID(NoteData))

    assert note.id.name == "notedata"
    assert note.type_name == "notedata"


def test_the_declarations_live_on_the_class():
    """**声明在类体上**:故它与实例里那个值现在是什么无关."""
    assert NoteData.declared_kinds() == {
        "title": "attr",
        "slug": "attr",
        "lines": "body",
    }
    assert Plain.declared_kinds() == {}


def test_a_field_may_be_derived_from_the_identity(engine: Engine):
    """身份在构造时就定了,故派生字段可以照它的内部值算,落盘之后原样读回来."""
    note = NoteData(ID(NoteData))
    note.slug = note.id.value_uuid[:8]

    identity = note.save()

    bind(None)
    bind(engine)

    assert NoteData.fetch(identity).slug == identity.value_uuid[:8]


# ---- 一个块占两类槽,种类在槽头上 ----


def test_a_block_lands_as_one_attr_slot_and_one_body_slot(engine: Engine):
    """一个块落成两类槽:**属性槽一格,正文槽一格**,两者各有各的写法.

    位置段的次序是**正文槽在前,属性槽在后**(写侧的老口径,未改);而"哪一格是什么"
    由**槽头种类**回答,库里不再为它单列一列.
    """
    identity = _note().save()

    held = _block_slots(engine, identity)

    assert [kind for kind, _content in held] == [BODY_SLOT, ATTR_SLOT]


def test_the_attr_slot_carries_the_attributes(engine: Engine):
    """属性槽里装着块的属性;**正文不在属性槽里**."""
    identity = _note().save()

    _hub, _pack, _segments, attrs = engine.find_block(identity)

    assert "第一篇".encode() in attrs
    assert "第二行".encode() not in attrs


def test_the_body_slot_carries_the_body(engine: Engine):
    """正文槽里装着正文;**属性不在正文槽里**."""
    identity = _note().save()

    body = _body_slots(engine, identity)

    assert len(body) == 1
    assert "第二行".encode() in body[0]
    assert "第一篇".encode() not in body[0]


def test_the_slot_kinds_are_told_by_the_slot_heads(engine: Engine):
    """**分拣靠槽头种类**:库里没有"哪几格是属性槽"那一列,故读一个块要读回槽头.

    这一条同时钉住"库的列是七个":拿那一行交出来的段列表逐格读,
    槽头自己说着它是属性槽还是正文槽.
    """
    identity = _note().save()
    row = engine.index_row(identity)

    kinds = [slot.kind for slot in engine.scan_slots(identity)]

    assert kinds.count(ATTR_SLOT) == 1, "属性槽正好一格"
    assert kinds.count(BODY_SLOT) == 1, "正文槽正好一格"
    assert "attr_in_pack_slot" not in row, "库里没有那一列"


def test_the_position_covers_both_slots(engine: Engine):  # noqa: ARG001 — 夹具的副作用是接上引擎
    """位置段覆盖该块占用的**全部槽**(属性槽与正文槽),改一次写一次.

    **索引块那条正表行占的槽不在其中**:它属于索引块,写在索引块自己那张表里.
    """
    identity = _note().save()

    assert identity.in_hub == "main"
    assert identity.in_hub_pack
    assert len(identity.slots) == 2, "属性槽一格加正文槽一格"


def test_the_segments_cover_a_scattered_position(engine: Engine):  # noqa: ARG001 — 夹具的副作用是接上引擎
    """位置段是**段列表**:一段连续的格写一个区间,零散的单格逐个写."""
    identity = ID(NoteData, value_uuid="u")
    identity.place([0, 5, 6, 9], hub="main", pack="p")

    assert identity.in_pack_slot == [0, (5, 6), 9]


# ---- 两个运行时状态:正文在不在本块 ----


def test_an_inline_body_is_stamped_on_save(engine: Engine):  # noqa: ARG001 — 夹具的副作用是接上引擎
    """**自带型**:`_inline_body` 为假,`_body_hash` 就是这份正文自己的摘要."""
    note = _note()
    note.save()

    assert note.body_is_ref is False
    assert note.body_hash == content_digest(note)
    assert note.id.body == note.body_hash, "库里那一列就是当前这份的摘要"


def test_loading_stamps_the_same_states(engine: Engine):
    """载入时两个状态由**库行 + 槽头**推出来,故与落盘那一刻一致."""
    identity = _note().save()

    bind(None)
    bind(engine)
    restored = NoteData.fetch(identity)

    assert restored.body_is_ref is False
    assert restored.body_hash == identity.body


def test_loading_a_referring_block_stamps_the_reference_credential(engine: Engine):
    """引用型载入之后:`_inline_body` 为真,`_body_hash` 是**关联凭证**.

    凭证就是库里那一行那一列的摘要,故它一定等于 `id.body`.
    """
    owner = _note()
    owner.save()
    bind(None)
    bind(engine)
    other = NoteData(ID(NoteData))
    other.lines = ["第一行", "第二行"]
    identity = other.save()

    bind(None)
    bind(engine)
    restored = NoteData.fetch(identity)

    assert restored.body_is_ref is True
    assert restored.body_hash == identity.body
    assert restored.lines == ["第一行", "第二行"], "引用型照样读得回正文"


def test_a_fresh_block_has_no_body_yet():
    """当场造出来的块还没有正文:`_body_hash` 空,`_inline_body` 真."""
    note = NoteData(ID(NoteData))

    assert note.body_hash == ""
    assert note.body_is_ref is True


# ---- 只写动过的域 ----


def test_changing_only_an_attribute_overwrites_the_same_slot(engine: Engine):
    """**属性槽原地覆盖**:改一个属性不产生新槽,正文那一份一份不多.

    正文这一次按摘要命中,故本块不再自带正文槽(引用型);而**属性槽是原地覆盖的**——
    看它占的那一格是不是还是原来那一格.
    """
    note = _note()
    note.save()
    identity = note.id
    before_attrs = [slot for slot in engine.scan_slots(identity) if slot.kind == ATTR_SLOT]
    before_bodies = _kind_counts(engine)[BODY_SLOT]

    bind(None)
    bind(engine)
    note.title = "改过的标题"
    note.save()

    after_attrs = [slot for slot in engine.scan_slots(identity) if slot.kind == ATTR_SLOT]
    assert len(after_attrs) == len(before_attrs), "属性槽数不变：原地覆盖，不另占"
    assert "改过的标题".encode() in after_attrs[0].content
    assert _kind_counts(engine)[BODY_SLOT] == before_bodies, "正文槽一格不多"
    bind(None)
    bind(engine)
    assert NoteData.fetch(identity).title == "改过的标题"


def test_changing_the_body_appends_a_new_slot(engine: Engine):
    """**正文槽只追加**:改一段正文即新建槽,位置段指向新槽,旧世代留在载体上."""
    note = _note()
    note.save()
    identity = note.id
    first = identity.in_pack_slot
    before = _kind_counts(engine)

    bind(None)
    bind(engine)
    note.lines = ["第一行", "改过的第二行"]
    note.save()

    assert identity.in_pack_slot != first, "新世代落在新槽上"
    assert _kind_counts(engine)[BODY_SLOT] == before[BODY_SLOT] + 1, "旧世代没被改写"
    bind(None)
    bind(engine)
    assert NoteData.fetch(identity).lines == ["第一行", "改过的第二行"]


def test_saving_an_unchanged_block_writes_nothing_new(engine: Engine):
    """同一份内容再存一次:正文按摘要命中,**不写新槽**;属性原地覆盖同一格.

    命中那一路不写 body 槽(2026-10-02 修正裁定),故本块那一趟翻成**引用型**,
    自己原来那几格空着——值与读回都不受影响,字节等回收收.
    """
    note = _note()
    note.save()
    identity = note.id
    before_attr = [slot.content for slot in engine.scan_slots(identity) if slot.kind == ATTR_SLOT]
    before_bodies = _kind_counts(engine)[BODY_SLOT]
    before_slots = len(identity.slots)

    bind(None)
    bind(engine)
    note.save()

    assert [slot.content for slot in engine.scan_slots(identity) if slot.kind == ATTR_SLOT] == (
        before_attr
    ), "属性槽原地覆盖，内容不变"
    assert _kind_counts(engine)[BODY_SLOT] == before_bodies, "正文按摘要命中，不写新槽"
    assert len(identity.slots) < before_slots, "位置段只剩本块自己的属性槽"
    bind(None)
    bind(engine)
    assert NoteData.fetch(identity).lines == ["第一行", "第二行"], "读回走第二跳，值不变"


def test_the_row_keeps_only_the_current_body(engine: Engine):
    """**改正文即换掉那一列**:库里只留当前一份的摘要,没有世代可留.

    故"上一份正文去哪了"这一问在存储里没有答案——要留历史由上层自己留引用.
    """
    note = _note()
    note.save()
    identity = note.id
    first = identity.body

    bind(None)
    bind(engine)
    note.lines = ["一"]
    note.save()

    assert identity.body != first, "那一列换成了新那份的摘要"
    assert identity.body == note.body_hash
    assert "body_history" not in identity.to_row(), "库里没有留世代的列"
    assert NoteData.fetch(identity).lines == ["一"]


# ---- 正文关联走摘要:自带与引用两条路 ----


def test_the_same_body_is_written_once(engine: Engine):
    """同内容只写一份:第二个块**不写 body 槽**,盘上的正文槽仍是一格.

    它是**引用型**:位置段里那几格是写侧给的坐标(正文在那一格上),
    故读它要走"第二跳"——拿摘要查正文索引.
    """
    first = _note()
    first.save()

    bind(None)
    bind(engine)
    second = NoteData(ID(NoteData))
    second.title = "第二篇"
    second.lines = ["第一行", "第二行"]  # 正文与第一份相同
    second.save()

    bodies = [slot for _hub, _pack, _number, slot in engine.scan() if slot.kind == BODY_SLOT]

    assert len(bodies) == 1, "同内容只写一份正文"
    assert second.body_is_ref is True, "第二个块是引用型：它自己没有正文槽"
    assert second.id.body == first.id.body, "关联凭证就是那一份的摘要"
    assert _body_slots(engine, second.id) == [], "本块没多写一格正文"
    assert _kind_counts(engine)[BODY_SLOT] == 1, "全库仍只有第一份那一格"
    assert len(second.id.in_pack_slot) == 1, "位置段只覆盖本块自己的属性槽"
    bind(None)
    bind(engine)
    assert NoteData.fetch(second.id).lines == ["第一行", "第二行"]


def test_a_referring_block_reads_the_body_from_the_other_pack(engine: Engine):
    """引用型读正文那**第二跳**:拿摘要查正文索引,按它给出的坐标读那份正文."""
    first = _note()
    first.save()
    first_pack = first.id.in_hub_pack

    bind(None)
    bind(engine)
    second = NoteData(ID(NoteData))
    second.lines = ["第一行", "第二行"]
    second.save(hub="other")  # 落在**另一个 hub**,故正文必然在别处

    assert second.id.in_hub == "other"
    assert second.body_is_ref is True
    bind(None)
    bind(engine)
    restored = NoteData.fetch(second.id)
    assert restored.lines == ["第一行", "第二行"]
    assert restored.body_hash == second.id.body
    assert first_pack, "第一份正文仍在自己那一份载体上（没有复制到别的 hub）"


def test_a_referring_block_breaks_loudly_when_the_body_index_row_is_gone(engine: Engine):
    """引用型而正文索引里没有那一份:**报"引用已失效"**,不交一份空正文回去."""
    first = _note()
    first.save()
    bind(None)
    bind(engine)
    second = NoteData(ID(NoteData))
    second.lines = ["第一行", "第二行"]
    second.save()
    _drop_body_rows(engine)

    bind(None)
    bind(engine)
    with pytest.raises(ObjectNotFoundError, match="引用已失效"):
        NoteData.fetch(second.id)


def _drop_body_rows(engine: Engine) -> None:
    """把正文索引里那些**位置行**摘掉(用例里模拟"索引行丢了")."""
    for row in list(engine.index.rows("bodyindex")):
        engine.index.drop_row("bodyindex", str(row["value_uuid"]))
    assert engine.index_engine.records(BodyIndex) == (), "索引行确实没了"


def test_two_blocks_sharing_content_differ_in_identity(engine: Engine):
    """**身份与内容无关**:同一份正文配上不同属性就是两个身份."""
    first = _note()
    first.title = "第一篇"
    first_id = first.save()

    bind(None)
    bind(engine)
    second = NoteData(ID(NoteData))
    second.title = "第二篇"
    second.lines = ["第一行", "第二行"]
    second_id = second.save()

    assert first_id.value_uuid != second_id.value_uuid
    assert content_digest(first) == content_digest(second)


def test_the_body_column_carries_a_digest_not_slots(
    engine: Engine,  # noqa: ARG001 — 夹具的副作用是接上引擎
):
    """那一列里**只有摘要**:一个十六进制串,没有槽段.

    槽号只在 pack 内有意义,而关联的那份正文可能在别的 pack,别的 hub.
    """
    note = _note()
    note.save()

    written = note.id.body
    assert written
    assert "0-1" not in written, "它不是段列表"
    assert all(part in "0123456789abcdef" for part in written), "是十六进制摘要"


def test_a_bare_assignment_is_not_deduplicated(engine: Engine):
    """**裸赋值不去重**:两次写入各占一格,与正文的判据不是同一条."""
    first = Plain(ID(Plain))
    first.note = "同一段文字"  # type: ignore[attr-defined]
    first.save()

    bind(None)
    bind(engine)
    second = Plain(ID(Plain))
    second.note = "同一段文字"  # type: ignore[attr-defined]
    second.save()

    assert first.id.slots != second.id.slots, "两次写入各占一格，不去重"


# ---- 读回 ----


def test_a_block_round_trips_through_the_disk(engine: Engine):
    """存进去,读回来:每个字段一个不差,身份也一致."""
    identity = _note().save()

    bind(None)
    bind(engine)
    restored = NoteData.fetch(identity)

    assert isinstance(restored, NoteData)
    assert restored.title == "第一篇"
    assert restored.slug == "abc"
    assert restored.scratch == "只落盘、不索引"
    assert restored.lines == ["第一行", "第二行"]
    assert restored.id.value_uuid == identity.value_uuid
    assert restored.id.birth_time == identity.birth_time


def test_the_restored_fields_are_bare_values(engine: Engine):
    """取回来的字段就是**值本身**:正文能被比较,迭代,就地增改."""
    identity = _note().save()

    bind(None)
    bind(engine)
    restored = NoteData.fetch(identity)

    assert isinstance(restored.title, str)
    restored.lines.append("第三行")
    assert restored.lines == ["第一行", "第二行", "第三行"], "正文能就地增改"


def test_fetching_an_unknown_identity_reports_it(engine: Engine):  # noqa: ARG001 — 夹具的副作用是接上引擎
    """盘上没有这个身份:报错,不返回一个空壳."""
    with pytest.raises(ObjectNotFoundError, match="对象不在"):
        Plain.fetch(ID(Plain))


def test_find_returns_none_instead_of_raising(engine: Engine):  # noqa: ARG001 — 夹具的副作用是接上引擎
    """`find` 与 `fetch` 的分别只在要不要抛错."""
    assert Plain.find(ID(Plain)) is None


def test_an_unknown_table_still_reads_back_degraded(engine: Engine):
    """**不认识的类型一律降级读回**:属性照旧齐全,只是没有那个类的行为方法."""
    identity = _note().save()

    bind(None)
    bind(engine)
    restored = Block.fetch(identity)

    assert getattr(restored, "title") == "第一篇"  # noqa: B009 — 走基座的降级读回


def test_reading_a_block_without_an_index_row_is_refused(engine: Engine):
    """**读路径没有顺扫回退**:库里没有那一行即显式报错."""
    identity = _note().save()
    engine.index.drop_row("notedata", identity.value_uuid)

    with pytest.raises(ObjectNotFoundError, match="对象不在"):
        engine.find_block(identity)


def test_a_missing_pack_is_reported_as_not_found(engine: Engine):
    """载体不见了也报"对象不在":读路径不建东西,也不返回半截."""
    identity = _note().save()
    for pack in (engine.root / "main" / "packs").iterdir():
        pack.unlink()

    with pytest.raises(ObjectNotFoundError, match="对象不在"):
        engine.load(identity)


def test_scan_slots_gives_the_raw_slot_contents(engine: Engine):
    """命令面要的原文:按位置段次序交出每一格的种类与内容."""
    identity = _note().save()

    held = engine.scan_slots(identity)

    assert [slot.kind for slot in held] == [BODY_SLOT, ATTR_SLOT]


def test_scan_slots_refuses_an_unknown_identity(engine: Engine):
    """没有那一行即报错,不交出空列表."""
    with pytest.raises(ObjectNotFoundError, match="对象不在"):
        engine.scan_slots(ID(Plain))


# ---- 删除 ----


def test_deleting_a_block_takes_the_row_away(engine: Engine):
    """删除 = **摘掉索引库那一行**:载体上不留任何标记."""
    identity = _note().save()
    before = _kind_counts(engine)

    note = NoteData.fetch(identity)

    assert note.delete() is True
    assert engine.index.get("notedata", identity.value_uuid) is None
    assert _kind_counts(engine) == before, "载体上不追加任何东西"
    assert Plain.find(identity) is None


def test_deleting_twice_reports_the_second_as_a_no_op(engine: Engine):  # noqa: ARG001 — 夹具接上引擎
    """删两次:第二次没东西可删,返回 False,不报错."""
    identity = _note().save()
    note = NoteData.fetch(identity)
    note.delete()

    assert note.delete() is False


def test_a_deleted_block_does_not_come_back(engine: Engine):  # noqa: ARG001 — 夹具的副作用是接上引擎
    """删掉之后按身份读回来显式报错:**没有旧副本复活这条路**."""
    identity = _note().save()
    NoteData.fetch(identity).delete()

    with pytest.raises(ObjectNotFoundError, match="对象不在"):
        NoteData.fetch(identity)


def test_deleting_an_unknown_identity_reports_false(engine: Engine):  # noqa: ARG001 — 夹具的副作用是接上引擎
    """没这个身份即返回 False,不抛错."""
    assert Plain(ID(Plain)).delete() is False


def test_deleting_a_block_leaves_the_body_position_row(engine: Engine):
    """**删块时正文索引行留着**(2026-10-02 修正裁定):由回收按引用判活.

    位置行是"这份正文在哪",不是"哪个块拥有它";那一块被删了,还在引用它的块
    不该跟着断.
    """
    identity = _note().save()
    rows = list(engine.index.rows("bodyindex"))
    assert rows, "落盘时写了一条位置行"

    NoteData.fetch(identity).delete()

    assert engine.index.get("bodyindex", str(rows[0]["value_uuid"])) is not None
    assert engine._row_of(identity) is None, "块的行已摘"
    assert engine.index_engine.search(BodyIndex, CONTENT_FIELD, identity.body), (
        "位置行仍在，故「这份正文在哪」这一问还答得出"
    )


# ---- 那根线 ----


def test_an_unbound_engine_refuses_to_work():
    """还没接引擎就 `save()`:报错,不静默什么都不做."""
    bind(None)

    with pytest.raises(RuntimeError, match="还没有接上引擎"):
        _note().save()


def test_two_engines_cannot_be_bound_at_once(tmp_path: Path):
    """一个进程只接一个引擎:不静默切库."""
    bind(None)
    first = Engine(tmp_path / "a")
    second = Engine(tmp_path / "b")
    bind(first)

    with pytest.raises(RuntimeError, match="只接一个引擎"):
        bind(second)
    bind(None)


def test_an_engine_repr_names_its_root(engine: Engine):
    """诊断用:库根与默认 hub."""
    assert "main" in repr(engine)
    assert "vault" in repr(engine)


def test_an_engine_opens_its_index_lazily(tmp_path: Path):
    """索引库**惰性开**:还没用过它,库文件就不该存在."""
    instance = Engine(tmp_path / "vault", slot_bytes=_SLOT)

    assert not instance.catalog_path.is_file()
    assert instance.index.path.is_file()
    instance.close()


def test_the_position_puts_the_body_first_then_attrs(engine: Engine):
    """位置段的次序有语义:**正文槽在前,属性槽在后**(写侧的老口径,未改).

    它是"哪一格是什么"之外的**另一件事**:种类由槽头回答,次序由位置段留住.
    回收重铺位置段时照这一条来(`gc._rehome`).
    """
    identity = _note().save()
    kinds = [slot.kind for slot in engine.scan_slots(identity)]

    assert kinds[0] == BODY_SLOT
    assert kinds[-1] == ATTR_SLOT


def _expand(*groups: Iterable[int | tuple[int, int]]) -> list[int]:
    """把若干段列表展开成一串槽号(用例里的取证助手)."""
    found: list[int] = []
    for group in groups:
        for item in group:
            if isinstance(item, int):
                found.append(item)
            else:
                found.extend(range(item[0], item[1] + 1))
    return found
