# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""GC 契约:**按索引库收活槽**,谁也带不走活的东西,死的东西一个都不留.

本文件钉七件事:

- **删除之后收得掉**:库里没有那一行,那些槽就是死字节,一趟扫完即消失;
- **活的东西一动不动地读得回来**:搬过位置的块仍能 `fetch`,值一字不差——
  这一条同时钉住"索引库被扶正"(位置是真源,搬完不扶正,读就指向旧字节);
- **一份正文被两个块共享时,删掉一个不减另一份**:引用按"还有没有块的摘要链指着它"判;
- **摘要链是活口的第二来源**:引用型块自己没有正文槽,正文的位置在正文索引的位置行里,
  回收要照摘要链把那一份正文算活,并把位置行扶正;
- **零散段收敛成整段**:回收把分散的槽搬成连续的一段,位置段随之归成规范形;
- **已经干净的书再扫一遍什么都不动**:没有死槽就不重写载体;
- **可叫停**:`should_stop` 返回真之后,剩下的 hub 保持原样.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.storage.db.id import ID
from core.storage.engine import Block, Engine, bind
from core.storage.gc import reclaimable_bytes, sweep
from core.storage.index.bodyindex import BodyIndex
from core.storage.index.index import CONTENT_FIELD
from core.storage.pack import ATTR_SLOT, BODY_SLOT
from core.storage.types import Attr, Body

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_SLOT = 512


class GcMemo(Block):
    """本文件用的块:一个可索引属性 + 一段正文."""

    title: str = Attr("")  # type: ignore[assignment]
    lines: list[str] = Body([])  # type: ignore[assignment]


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """接上一个干净的引擎,并把这根线接通(用例结束解开并关掉连接)."""
    instance = Engine(tmp_path / "vault", slot_bytes=_SLOT)
    bind(instance)
    yield instance
    bind(None)
    instance.close()


def _memo(title: str, lines: list[str] | None = None) -> GcMemo:
    """造一个填好的块."""
    memo = GcMemo(ID(GcMemo))
    memo.title = title
    memo.lines = [] if lines is None else lines
    return memo


def _slots(engine: Engine) -> int:
    """全库的槽数."""
    return sum(1 for _hub, _pack, _number, _slot in engine.scan())


def _body_slots(engine: Engine) -> int:
    """全库的正文槽数."""
    return sum(1 for _hub, _pack, _number, slot in engine.scan() if slot.kind == BODY_SLOT)


def _bytes(engine: Engine) -> int:
    """全部载体的总字节数."""
    total = 0
    for hub in engine.root.iterdir():
        if not hub.is_dir():
            continue
        packs = hub / "packs"
        if not packs.is_dir():
            continue
        total += sum(entry.stat().st_size for entry in packs.iterdir())
    return total


def test_sweep_reclaims_a_deleted_block(engine: Engine):
    """删掉一个块之后扫一趟:它那些槽全都不在了,空间确实变小."""
    memo = _memo("要走", ["一行正文"])
    memo.save()
    memo.delete()
    before = _bytes(engine)

    report = sweep(engine)

    assert report.cancelled is False
    assert report.reclaimed > 0
    assert _bytes(engine) == before - report.reclaimed
    assert engine._row_of(memo.id) is None


def test_live_blocks_survive_and_still_read_back(engine: Engine):
    """活着的块被搬到新载体之后照样读得回来:位置变了,值不变."""
    keep = _memo("留着", ["第一行"])
    keep.save()
    gone = _memo("要走", ["别的一行"])
    gone.save()
    gone.delete()

    sweep(engine)

    again = GcMemo.fetch(keep.id)
    assert again.title == "留着"
    assert again.lines == ["第一行"]
    assert GcMemo.find(gone.id) is None


def test_shared_content_survives_one_of_its_holders(engine: Engine):
    """同一份正文挂在两个块上:删掉一个,另一个照样读得到那份正文.

    第二个块是**引用型**:它自己没有正文槽,正文的位置在正文索引的位置行里;
    "还有人要它"由第一个块的摘要链现算——**位置不挂在块身上**,故删谁都不断别人.
    """
    left = _memo("左", ["同一段"])
    left.save()
    right = _memo("右", ["同一段"])
    right.save()

    left.delete()
    sweep(engine)

    assert GcMemo.fetch(right.id).lines == ["同一段"]


def test_sweep_drops_the_index_rows_of_deleted_blocks(engine: Engine):
    """删掉的块在正文索引里那一行也要摘掉:留着它就会把已删的块又"查"回来."""
    memo = _memo("要走", ["一段正文"])
    memo.save()
    place = engine._row_of(memo.id)
    assert place is not None
    digest = str(engine.index_engine.search(BodyIndex, CONTENT_FIELD, _digest_of(memo))[0]["value"])
    memo.delete()

    sweep(engine)

    assert engine.index.get("gcmemo", memo.id.value_uuid) is None
    assert engine.index_engine.search(BodyIndex, CONTENT_FIELD, digest.partition(":")[2]) == ()


def test_a_body_nobody_references_is_collected(engine: Engine):
    """**没有块再要的正文**:回收摘掉它那一行位置行,正文槽也随之收走.

    位置行是推导出来的坐标,不是内容本身,故"还有没有摘要链指着它"是它该不该在的
    唯一判据.
    """
    memo = _memo("要走", ["一段正文"])
    memo.save()
    assert _body_slots(engine) == 1

    memo.delete()
    sweep(engine)

    assert engine.index_engine.records(BodyIndex) == (), "位置行已摘"
    assert _body_slots(engine) == 0, "正文槽也收走了"


def test_a_referenced_body_survives_its_owner(engine: Engine):
    """**引用型块的正文不会因为原主被删而消失**:回收按摘要链判活."""
    owner = _memo("原主", ["共享的一段"])
    owner.save()
    other = _memo("引用者", ["共享的一段"])
    other.save()
    assert other.body_is_ref is True

    owner.delete()
    sweep(engine)

    assert GcMemo.fetch(other.id).lines == ["共享的一段"]
    assert _body_slots(engine) == 1, "那一份正文还在"


def _digest_of(block: Block) -> str:
    """这个块的正文摘要(用例里只用来定位那一行)."""
    from core.storage.engine import content_digest  # noqa: PLC0415 — 只在这一处用到

    found = content_digest(block)
    assert found is not None
    return found


def test_a_clean_library_is_left_alone(engine: Engine):
    """已经干净的书再扫一遍:不重写载体,数字一个都不变."""
    _memo("甲", ["一"]).save()
    _memo("乙", ["二"]).save()

    first = sweep(engine)

    assert first.reclaimed == 0
    assert first.packs_before == first.packs_after
    second = sweep(engine)
    assert second.reclaimed == 0
    assert second.slots_before == second.slots_after


def test_repeated_saves_leave_only_the_live_slots(engine: Engine):
    """同一个块存三次(正文换了两次):趟过之后只留现役的那一份正文,读回来是最后那份值."""
    memo = _memo("初稿")
    memo.save()
    memo.title = "二稿"
    memo.save()
    memo.title = "定稿"
    memo.lines = ["最后一行"]
    memo.save()
    identity = memo.id
    before = _slots(engine)

    sweep(engine)

    assert _slots(engine) < before, "旧世代与旧属性槽都是死字节"
    assert GcMemo.fetch(identity).title == "定稿"
    assert GcMemo.fetch(identity).lines == ["最后一行"]


def test_the_old_generation_within_the_depth_is_kept(engine: Engine):
    """**保护旧世代**:保留范围之内(`body.history.depth`)的世代算活口,不得被收走."""
    memo = _memo("甲", ["第一世代"])
    memo.save()
    first_body = memo.id.body_history[0]

    bind(None)
    bind(engine)
    memo.lines = ["第二世代"]
    memo.save()
    second_body = memo.id.body_history[0]
    assert first_body != second_body

    sweep(engine)

    bind(None)
    bind(engine)
    assert GcMemo.fetch(memo.id).lines == ["第二世代"], "现役那一份必须还在"


def test_a_dirty_library_reports_reclaimable_bytes(engine: Engine):
    """可回收的字节数由"死槽那几格"算出:删掉一块之后它大于零."""
    memo = _memo("要走", ["一段"])
    memo.save()
    assert reclaimable_bytes(engine) == 0, "入库之后没有死槽"

    memo.delete()

    assert reclaimable_bytes(engine) > 0


def test_should_stop_leaves_the_rest_alone(engine: Engine):
    """叫停之后剩下的 hub 保持原样:已处理的收干净,没碰的一个字节不动."""
    first = _memo("甲")
    first.save(hub="aaa")
    second = _memo("乙")
    second.save(hub="bbb")
    first.delete()
    second.delete()

    report = sweep(engine, should_stop=lambda: True)

    assert report.cancelled is True
    assert report.reclaimed == 0
    assert engine.index.get("gcmemo", first.id.value_uuid) is None, "一个 hub 都没处理"
    assert _slots(engine) > 0, "没碰的字节一个都不动"


def test_stopping_after_the_first_hub_keeps_the_rest_untouched(engine: Engine):
    """叫停在第一个 hub 之后:那一份收干净,没碰的照旧,而索引库两边都对得上."""
    gone = _memo("甲")
    gone.save(hub="aaa")
    gone.delete()
    keep = _memo("乙", ["别的一行"])
    keep.save(hub="bbb")
    seen = {"calls": 0}

    def stop() -> bool:
        """第一次问(还没动任何 hub)返回假,第二次问返回真."""
        seen["calls"] += 1
        return seen["calls"] > 1

    report = sweep(engine, should_stop=stop)

    assert report.cancelled is True
    assert report.reclaimed > 0, "第一个 hub（aaa）里的死槽被收掉了"
    assert GcMemo.find(gone.id) is None
    assert GcMemo.fetch(keep.id).lines == ["别的一行"], "没碰的那个 hub 照旧读得回来"


def test_progress_is_reported_per_hub(engine: Engine):
    """每处理完一个 hub 报一次:参数是(已完成,总数),界面按它显示进度.

    **索引块落在默认 hub 里**(写索引时不点名),故两个块各进一个 hub 时,
    全库因此是三个 hub——这不是多余的一份,是索引自己的家.
    """
    _memo("甲").save(hub="aaa")
    _memo("乙").save(hub="bbb")
    seen: list[tuple[int, int]] = []

    report = sweep(engine, on_progress=lambda done, total: seen.append((done, total)))

    assert report.hubs == ("aaa", "bbb", "main")
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_sweep_collects_a_scattered_position_into_one_run(engine: Engine):
    """**零散段收敛成整段**:同一块分散在多处的槽,回收这一趟搬成连续的两段.

    段至多两处:**正文槽一段,属性槽一段**(写侧的次序).回收把每一段各自并成一段,
    故搬完之后位置段就是至多两段,而"零散的单格"一个都不剩.
    """
    first = _memo("甲", ["一"])
    first.save()
    second = _memo("乙", ["二"])
    second.save()
    second.delete()

    sweep(engine)

    assert len(first.id.in_pack_slot) <= 2, "至多两段：正文槽一段、属性槽一段"
    assert first.id.body_history, "摘要链还在"
    bind(None)
    bind(engine)
    assert GcMemo.fetch(first.id).lines == ["一"]


def test_a_report_carries_both_calibers(engine: Engine):
    """报告按载体与按槽两条口径各给一份数字,另加 `reclaimed`."""
    _memo("甲", ["一"]).save()

    report = sweep(engine)

    assert report.packs_before >= report.packs_after
    assert report.slots_before >= report.slots_after
    assert report.reclaimed == report.bytes_before - report.bytes_after
    assert report.hubs


def test_sweep_on_an_empty_vault_does_nothing(tmp_path: Path):
    """一份载体都没有的库:扫一趟什么都不做,也不报错."""
    instance = Engine(tmp_path / "vault", slot_bytes=_SLOT)

    report = sweep(instance)

    assert report.packs_before == 0
    assert report.reclaimed == 0
    assert report.cancelled is False
    instance.close()


def test_a_swept_block_reads_back_from_the_new_position(engine: Engine):
    """搬动之后库里那一行指着新位置:从头读一遍走的全是新字节."""
    memo = _memo("留着", ["一段正文"])
    memo.save()
    identity = memo.id

    sweep(engine)

    bind(None)
    bind(engine)
    restored = GcMemo.fetch(identity)
    assert restored.title == "留着"
    assert restored.lines == ["一段正文"]
    assert all(slot.kind in {ATTR_SLOT, BODY_SLOT} for slot in engine.scan_slots(identity))
