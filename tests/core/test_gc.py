# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""GC 契约：谁也带不走活的东西，死的东西一个都不留。

本文件钉五件事（每条都是"回收"这个动作的判据）：

- **删掉的字节真被收走**：墓碑与它标记的块记录一起消失，空间确实回给文件系统；
- **活的东西一动不动地读得回来**：搬过位置的块仍能 `fetch`，值一字不差——
  这一条同时钉住"索引库被扶正"（位置是投影，搬完不扶正，读就退化成扫全库）；
- **一份内容被两个块共享时，删掉一个不减另一份**：引用数按"谁还指着它"判；
- **已经干净的书再扫一遍什么都不动**：没有死记录就不重写载体；
- **可叫停**：`should_stop` 返回真之后，剩下的 hub 保持原样。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.storage.db.id import ID
from core.storage.db.payload import decode_block, decode_index, decode_tombstone
from core.storage.engine import Block, Engine, bind, content_digest
from core.storage.gc import sweep
from core.storage.index.bodyindex import BodyIndex
from core.storage.index.index import CONTENT_FIELD
from core.storage.types import Attr, Body

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class GcMemo(Block):
    """本文件用的块：一个可索引属性 + 一段内容。"""

    title: str = Attr("")  # type: ignore[assignment]
    lines: list[str] = Body([])  # type: ignore[assignment]


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """接上一个干净的引擎，并把这根线接通（用例结束解开并关掉连接）。"""
    instance = Engine(tmp_path / "vault", slot_bytes=512)
    bind(instance)
    yield instance
    bind(None)
    instance.close()


def _memo(title: str, lines: list[str] | None = None) -> GcMemo:
    """造一个填好的块。"""
    memo = GcMemo(ID(GcMemo))
    memo.title = title
    memo.lines = [] if lines is None else lines
    return memo


def _kind(payload: bytes) -> str:
    """这条载荷是哪一类记录。四类各有自己的保留键，判据一起比。"""
    if decode_block(payload) is not None:
        return "block"
    if decode_index(payload) is not None:
        return "index"
    if decode_tombstone(payload) is not None:
        return "tombstone"
    return "content"


def _counts(engine: Engine) -> dict[str, int]:
    """盘上四类记录各有多少条。"""
    found = {"block": 0, "content": 0, "index": 0, "tombstone": 0}
    for record in engine.scan():
        found[_kind(record.payload)] += 1
    return found


def _bytes(engine: Engine) -> int:
    """全部载体的总字节数。"""
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
    """删掉一个块之后扫一趟：墓碑与那条块记录都消失，空间确实变小。"""
    memo = _memo("要走")
    memo.save()
    memo.delete()
    before = _bytes(engine)

    report = sweep(engine)

    assert report.cancelled is False
    assert report.reclaimed > 0
    assert _bytes(engine) == before - report.reclaimed
    after = _counts(engine)
    assert after["tombstone"] == 0, "墓碑标记的那些字节这一趟就没了，留着它是死重量"
    assert after["block"] == 0
    assert after["content"] == 0, "没人指着的内容也一并收走"
    assert engine.find_block(memo.id) is None


def test_live_blocks_survive_and_still_read_back(engine: Engine):
    """活着的块被搬到新载体之后照样读得回来：位置变了，值不变。"""
    keep = _memo("留着", ["第一行"])
    keep.save()
    gone = _memo("要走", ["别的一行"])
    gone.save()
    gone.delete()

    sweep(engine)

    again = GcMemo.fetch(keep.id)
    assert again.title == "留着"
    assert again.lines == ["第一行"]
    assert engine.find_block(gone.id) is None


def test_shared_content_survives_one_of_its_holders(engine: Engine):
    """同一份内容挂在两个块上：删掉一个，另一个照样读得到那份内容。"""
    left = _memo("左", ["同一段"])
    right = _memo("右", ["同一段"])
    left.save()
    right.save()
    assert _counts(engine)["content"] == 1, "同内容只写一条，这是去重的前提"

    left.delete()
    sweep(engine)

    assert _counts(engine)["content"] == 1, "还有人在用，就不该收走"
    assert GcMemo.fetch(right.id).lines == ["同一段"]


def test_sweep_drops_the_index_rows_of_deleted_blocks(engine: Engine):
    """删掉的块在索引库里那一行也要摘掉：留着它就会把已删的块又"查"回来。"""
    memo = _memo("要走")
    memo.save()
    place = content_digest(memo)
    memo.delete()

    sweep(engine)

    assert place is not None
    assert engine.index.get("gcmemo", memo.id.value_uuid) is None
    assert engine.index_engine.search(BodyIndex, CONTENT_FIELD, place) == ()


def test_a_clean_library_is_left_alone(engine: Engine):
    """已经干净的书再扫一遍：不重写载体，数字一个都不变。"""
    _memo("甲", ["一"]).save()
    _memo("乙", ["二"]).save()

    first = sweep(engine)

    assert first.reclaimed == 0
    assert first.packs_before == first.packs_after
    second = sweep(engine)
    assert second.reclaimed == 0
    assert second.records_before == second.records_after


def test_repeated_saves_leave_only_the_head(engine: Engine):
    """同一个块存三次：趟过之后只留"最后写的"那一条，读回来还是最后那份值。"""
    memo = _memo("初稿")
    memo.save()
    memo.title = "二稿"
    memo.save()
    memo.title = "定稿"
    memo.save()
    assert _counts(engine)["block"] == 3

    sweep(engine)

    assert _counts(engine)["block"] == 1
    assert GcMemo.fetch(memo.id).title == "定稿"


def test_should_stop_leaves_the_rest_alone(engine: Engine):
    """叫停之后剩下的 hub 保持原样：已处理的收干净，没碰的一个字节不动。"""
    first = _memo("甲")
    first.save(hub="aaa")
    second = _memo("乙")
    second.save(hub="bbb")
    first.delete()
    second.delete()

    report = sweep(engine, should_stop=lambda: True)

    assert report.cancelled is True
    assert report.reclaimed == 0
    assert _counts(engine)["tombstone"] == 2, "一个 hub 都没处理，墓碑都还在"


def test_stopping_after_the_first_hub_keeps_the_rest_untouched(engine: Engine):
    """叫停在第一个 hub 之后：那一份收干净，没碰的照旧，而索引库两边都对得上。

    这一条钉的是"部分完成也算完成"：`_Live` 先把每个身份的**原位置**记下来，
    搬动过的再改写，故没被处理的 hub 在库里那一行仍然指着原来的坐标。
    """
    gone = _memo("甲")
    gone.save(hub="aaa")
    gone.delete()
    keep = _memo("乙", ["别的一行"])
    keep.save(hub="bbb")
    seen = {"calls": 0}

    def stop() -> bool:
        """第一次问（还没动任何 hub）返回假，第二次问返回真。"""
        seen["calls"] += 1
        return seen["calls"] > 1

    report = sweep(engine, should_stop=stop)

    assert report.cancelled is True
    assert report.reclaimed > 0, "第一个 hub（aaa）里的墓碑与已删块记录被收掉了"
    assert engine.find_block(gone.id) is None
    assert GcMemo.fetch(keep.id).lines == ["别的一行"], "没碰的那个 hub 照旧读得回来"


def test_progress_is_reported_per_hub(engine: Engine):
    """每处理完一个 hub 报一次：参数是（已完成，总数），界面按它显示进度。

    **索引块落在默认 hub 里**（写索引时不点名），故两个块各进一个 hub 时，
    全库因此是三个 hub——这不是多余的一份，是索引自己的家。
    """
    _memo("甲").save(hub="aaa")
    _memo("乙").save(hub="bbb")
    seen: list[tuple[int, int]] = []

    report = sweep(engine, on_progress=lambda done, total: seen.append((done, total)))

    assert report.hubs == ("aaa", "bbb", "main")
    assert seen == [(1, 3), (2, 3), (3, 3)]
