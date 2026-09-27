# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""桶与多桶：目录是事实、登记是投影；先落字节、后记目录。

覆盖四件事：

- 桶是**无状态**的一层：形态由目录给出，索引库里的桶表只是登记；
- 多桶对上层只是一次分组：分完组之后，剩下的全是"按槽区间读块"这一件事；
- 物理坐标是投影：索引里的位置由写入结果给出，丢了可以顺扫重建（档一）；
- 名字是数据：桶名与载体名都要拼路径，故都在入口处挡住越界形态。
"""

from __future__ import annotations

import shutil
import sqlite3
from typing import TYPE_CHECKING

import pytest

from core.conf import conf as engine_conf
from core.storage import Record
from core.storage.vault import DEFAULT_BUCKET, PACKS_DIR, Bucket, Placement, Vault
from core.types import (
    BucketExistsError,
    BucketNotFoundError,
    CorruptObjectError,
    Id,
    ObjectNotFoundError,
    RecordFormatError,
    SlotRange,
    StorageError,
    ValueHash,
    ValueUuid,
)

if TYPE_CHECKING:
    from pathlib import Path

_SLOT = 64 * 1024
"""造记录时用的槽长：只需不小于记录长度（载体按自己的文件头解释，见 §5.5）。"""


def _record(payload: bytes, *, name: str = "") -> Record:
    """一条自检过的记录：身份按内容签发，载荷即内容。"""
    return Record.create(Id.new(payload, name=name), payload, _SLOT)


def _same_identity(base: Id, payload: bytes) -> Id:
    """同一身份换一份内容：内容变不改变 ID（§3.3 第 3 条）。"""
    return Id(
        value_uuid=base.value_uuid,
        value_hash=ValueHash.of(payload),
        name=base.name,
        issued=base.issued,
    )


def _vault(tmp_path: Path, *, pack_max_bytes: int | None = None) -> Vault:
    return Vault.open(tmp_path / "vault", pack_max_bytes=pack_max_bytes)


# ---- 开库与对齐 ----


def test_open_creates_and_aligns_the_index(tmp_path: Path) -> None:
    """开库即对齐声明：索引库建好、无差异、声明投影可校验。"""
    with _vault(tmp_path) as vault:
        assert (vault.root / "catalog.db").is_file()
        assert vault.index.differences() == []
        vault.verify()


def test_open_refuses_a_foreign_sqlite_file(tmp_path: Path) -> None:
    """位置上压着别人的 SQLite 库 → 拒开，不往里建表（与配置端同一口径）。"""
    root = tmp_path / "vault"
    root.mkdir()
    stranger = sqlite3.connect(str(root / "catalog.db"))
    stranger.execute("CREATE TABLE strangers(x INTEGER)")
    stranger.commit()
    stranger.close()

    with pytest.raises(StorageError, match="不接管"):
        Vault.open(root)


# ---- 桶：目录是事实 ----


def test_bucket_is_created_on_demand_and_registered(tmp_path: Path) -> None:
    """取桶即建目录（带 ``packs/``）并把登记行补进索引库。"""
    with _vault(tmp_path) as vault:
        bucket = vault.bucket("notes")
        assert (bucket.root / PACKS_DIR).is_dir()
        assert [row["name"] for row in vault.bucket_rows()] == ["notes"]
        assert vault.register(bucket) is False  # 再取一次不重复登记


def test_bucket_address_may_be_a_name_or_an_id_shape(tmp_path: Path) -> None:
    """桶的地址就是目录名：取人话还是取 ID 形态，对查询没有区别。"""
    with _vault(tmp_path) as vault:
        named = vault.bucket("main")
        shaped = vault.bucket(str(ValueUuid.new()))
        assert named.name == DEFAULT_BUCKET
        assert sorted(item.name for item in vault.buckets()) == sorted([named.name, shaped.name])


def test_bucket_name_with_a_separator_is_refused(tmp_path: Path) -> None:
    """桶名会拼成路径，故带分隔符或上跳的名字在入口即拒。"""
    with _vault(tmp_path) as vault:
        for bad in ("../escape", "a/b", "..", "", "a\\b"):
            with pytest.raises(StorageError, match="桶名"):
                vault.bucket(bad)


def test_plain_directory_is_not_adopted_as_a_bucket(tmp_path: Path) -> None:
    """库里还会有别的东西：只有带 ``packs/`` 的直接子目录才算桶。"""
    with _vault(tmp_path) as vault:
        (vault.root / "别的东西").mkdir()
        assert vault.buckets() == ()
        with pytest.raises(StorageError, match="不是桶"):
            vault.bucket("别的东西")


def test_bucket_create_and_open_are_two_different_acts(tmp_path: Path) -> None:
    """建目录与开目录分开：``create`` 不接管已有目录，``open`` 不建目录。"""
    target = tmp_path / "bucket"
    Bucket.create(target)
    with pytest.raises(BucketExistsError):
        Bucket.create(target)
    Bucket.open(target)
    with pytest.raises(BucketNotFoundError):
        Bucket.open(tmp_path / "nowhere")


def test_reconcile_reports_rows_without_a_directory(tmp_path: Path) -> None:
    """登记对账：目录里有的补登记，登记里有的只报告不删。"""
    with _vault(tmp_path) as vault:
        vault.bucket("gone")
        (vault.root / "appeared" / PACKS_DIR).mkdir(parents=True)
        (vault.root / "gone" / PACKS_DIR).rmdir()
        (vault.root / "gone").rmdir()

        assert vault.reconcile() == ["gone"]
        assert [row["name"] for row in vault.bucket_rows()] == ["appeared", "gone"]


# ---- 记录：写入与读取 ----


def test_put_then_get_roundtrip(tmp_path: Path) -> None:
    """写入一条记录：索引行按**实际写入位置**填，读回的是同一条。"""
    with _vault(tmp_path) as vault:
        record = _record(b"hello cairn")
        place = vault.put(record, kind="notedata")

        assert place.bucket == DEFAULT_BUCKET
        assert place.pack.endswith(".pack")
        assert place.size == record.total_len

        row = vault.index.record_row(str(record.id.value_uuid))
        assert row is not None
        assert row["kind"] == "notedata"
        assert row["bucket"] == place.bucket
        assert row["pack"] == place.pack
        assert row["slot_start"] == place.span.start
        assert row["slot_head"] == place.span.head
        assert row["slot_count"] == place.span.count
        assert row["issued"] == record.id.issued

        assert vault.get(str(record.id.value_uuid)) == record
        assert vault.placement(str(record.id.value_uuid)) == place


def test_two_records_in_one_slot_are_read_back_apart(tmp_path: Path) -> None:
    """同槽共存的两条记录必须能各读各的（槽内偏移就是为这件事留的）。"""
    with _vault(tmp_path) as vault:
        first, second = _record(b"first"), _record(b"second")
        one = vault.put(first)
        two = vault.put(second)

        assert one.pack == two.pack
        assert one.span.start == two.span.start == 0
        assert one.span.head == 0
        assert two.span.head == first.total_len

        assert vault.get(str(second.id.value_uuid)) == second
        assert vault.get(str(first.id.value_uuid)) == first


def test_put_again_same_identity_moves_and_keeps_created(tmp_path: Path) -> None:
    """同一身份重写：位置改到新处，落盘时刻保留，类型不被空值抹掉。"""
    with _vault(tmp_path) as vault:
        base = Id.new(b"v1")
        first = vault.put(Record.create(base, b"v1", _SLOT), kind="notedata")
        row = vault.index.record_row(str(base.value_uuid))
        assert row is not None
        created = int(row["created"])

        changed = _same_identity(base, b"v2")
        second = vault.put(Record.create(changed, b"v2", _SLOT))

        row = vault.index.record_row(str(base.value_uuid))
        assert row is not None
        assert int(row["created"]) == created  # 首次落盘时刻
        assert int(row["updated"]) >= created
        assert row["kind"] == "notedata"  # 本次没带类型，不等于类型不存在
        assert row["value_hash"] == str(ValueHash.of(b"v2"))
        assert (second.pack, second.span) != (first.pack, first.span)
        assert vault.get(str(base.value_uuid)).payload == b"v2"


def test_get_unknown_id_raises(tmp_path: Path) -> None:
    with _vault(tmp_path) as vault, pytest.raises(ObjectNotFoundError):
        vault.get(str(ValueUuid.new()))


def test_get_of_a_vanished_bucket_raises(tmp_path: Path) -> None:
    """读路径不悄悄建桶：目录没了就要报出来。"""
    with _vault(tmp_path) as vault:
        record = _record(b"x")
        vault.put(record)
        shutil.rmtree(vault.root / DEFAULT_BUCKET)

        with pytest.raises(BucketNotFoundError):
            vault.get(str(record.id.value_uuid))


def test_missing_carrier_is_reported_as_corrupt(tmp_path: Path) -> None:
    """索引指着一个盘上没有的载体：宁可报损坏，也不假装读不出来是正常的。"""
    with _vault(tmp_path) as vault:
        record = _record(b"x")
        vault.put(record)
        vault.bucket(DEFAULT_BUCKET).packs()[0].path.unlink()

        with pytest.raises(CorruptObjectError, match="载体缺失"):
            vault.get(str(record.id.value_uuid))


def test_pack_name_cannot_escape_the_bucket(tmp_path: Path) -> None:
    """载体名来自索引（数据），故在拼路径之前挡住越界形态。"""
    with _vault(tmp_path) as vault:
        bucket = vault.bucket()
        for bad in ("../evil.pack", "sub/evil.pack", "", ".."):
            with pytest.raises(StorageError, match="载体名"):
                bucket.read(bad, SlotRange(0, 1))


# ---- 载体：随机名与封口线 ----


def test_pack_names_are_random_and_unique(tmp_path: Path) -> None:
    """载体名是随机串：无语义、无顺序号，故不会被当成"第几个"来用。"""
    with _vault(tmp_path, pack_max_bytes=1) as vault:
        for _ in range(3):
            vault.put(_record(b"x"))
        bucket = vault.bucket()
        names = [carrier.path.name for carrier in bucket.packs()]
        assert len(names) == 3
        assert len(set(names)) == 3
        assert all(name.endswith(".pack") for name in names)


def test_seal_line_starts_a_new_carrier(tmp_path: Path) -> None:
    """写满即换新载体：封口线取 1 时，一条记录一个载体。"""
    with _vault(tmp_path, pack_max_bytes=1) as vault:
        first = vault.put(_record(b"one"))
        second = vault.put(_record(b"two"))
        assert first.pack != second.pack


def test_active_picks_the_fullest_carrier_with_room(tmp_path: Path) -> None:
    """活跃载体＝有空间的最满者：封口线调大后仍有唯一答案（不靠时间戳与名字顺序）。

    这条规则让"封口线被调大"不必有专门处理：旧载体只要还有空间就重新可用，
    而这无害——记录落在哪个载体只是投影，位置由索引给出。
    """
    with _vault(tmp_path, pack_max_bytes=1) as vault:
        first = vault.put(_record(b"a" * 500))
        small = _record(b"b")
        second = vault.put(small)
        assert first.pack != second.pack

        reopened = Bucket.open(vault.root / DEFAULT_BUCKET, pack_max_bytes=1 << 30)
        assert reopened.active().path.name == first.pack  # 更满的那个先填满
        assert reopened.append(_record(b"c")).pack == first.pack
        assert vault.get(str(small.id.value_uuid)) == small  # 索引不受影响


def test_slot_bytes_come_from_the_carrier_not_from_config(tmp_path: Path) -> None:
    """槽长随载体走：读的时候按文件头解释偏移，不与当前配置对账（§5.5）。"""
    with _vault(tmp_path) as vault:
        record = _record(b"written before the config changed")
        place = vault.put(record)
        original = engine_conf.get("storage.pack.slot_bytes")
        try:
            engine_conf.set("storage.pack.slot_bytes", original * 4)
            # 配置换了，老载体仍按自己文件头里的槽长解释，故位置与读回的内容照旧成立。
            assert vault.get(str(record.id.value_uuid)) == record
            assert vault.placement(str(record.id.value_uuid)) == place
        finally:
            engine_conf.set("storage.pack.slot_bytes", original)


# ---- 多桶 ----


def test_two_buckets_are_independent(tmp_path: Path) -> None:
    """多桶＝一次分组：同一个库里记录按桶分开，读取按行里的桶名路由。"""
    with _vault(tmp_path) as vault:
        left, right = _record(b"left"), _record(b"right")
        here = vault.put(left, bucket="a")
        there = vault.put(right, bucket="b")

        assert (here.bucket, there.bucket) == ("a", "b")
        assert here.pack != there.pack
        assert vault.get(str(left.id.value_uuid)) == left
        assert vault.get(str(right.id.value_uuid)) == right
        assert {item.name for item in vault.buckets()} == {"a", "b"}


def test_scan_walks_every_bucket_or_only_one(tmp_path: Path) -> None:
    """顺扫是重建的入口：可以不看索引，把全库（或某个桶）的记录读一遍。"""
    with _vault(tmp_path) as vault:
        records = [_record(b"a1"), _record(b"b1"), _record(b"a2")]
        vault.put(records[0], bucket="a")
        vault.put(records[1], bucket="b")
        vault.put(records[2], bucket="a")

        assert {record for _place, record in vault.records()} == set(records)
        in_a = list(vault.records(bucket="a"))
        assert {record for _place, record in in_a} == {records[0], records[2]}
        assert all(place.bucket == "a" for place, _found in in_a)


def test_placements_from_a_scan_match_the_written_ones(tmp_path: Path) -> None:
    """顺扫给出的物理坐标必须与写入时算出的那个一致——重建正是靠这一条接回去。"""
    with _vault(tmp_path) as vault:
        written = [vault.put(_record(payload)) for payload in (b"one", b"two", b"three")]
        assert [place for place, _found in vault.records()] == written


# ---- 档一重建 ----


def test_rebuild_restores_missing_rows_and_keeps_existing_ones(tmp_path: Path) -> None:
    """重建只补缺行：类型不在记录头里，故已有的行一律不动。"""
    with _vault(tmp_path) as vault:
        kept, lost = _record(b"kept"), _record(b"lost")
        vault.put(kept, kind="notedata")
        vault.put(lost, kind="notedata")
        vault.index.conn.execute(
            "DELETE FROM record WHERE value_uuid = ?", (str(lost.id.value_uuid),)
        )
        vault.index.commit()

        assert vault.rebuild_records() == 1

        row = vault.index.record_row(str(lost.id.value_uuid))
        assert row is not None
        assert row["kind"] == ""  # 记录头里没有类型（§3.5）
        assert row["issued"] == lost.id.issued  # 身份与签发时刻能还原
        back = vault.index.record_row(str(kept.id.value_uuid))
        assert back is not None
        assert back["kind"] == "notedata"  # 已有的行没被动过
        assert vault.get(str(lost.id.value_uuid)) == lost


def test_rebuild_is_idempotent(tmp_path: Path) -> None:
    with _vault(tmp_path) as vault:
        vault.put(_record(b"one"))
        assert vault.rebuild_records() == 0


def test_rebuild_stops_at_a_truncated_carrier(tmp_path: Path) -> None:
    """坏点即停并报错：顺扫不得跳过读不出来的字节（跳过就把损坏伪装成缺失）。"""
    with _vault(tmp_path) as vault:
        vault.put(_record(b"one"))
        pack = vault.bucket().packs()[0].path
        pack.write_bytes(pack.read_bytes()[:-2])
        with pytest.raises(RecordFormatError):
            vault.rebuild_records()


def test_placement_is_not_persisted_in_the_record() -> None:
    """物理坐标不进记录：它是投影，不是事实（§9.2）。"""
    persisted = _record(b"payload").id.record()
    for key in ("slot", "pack_path", "file_path", "file_name", "net_ip"):
        assert not any(key in name for name in persisted)


def test_placement_equality_is_positional(tmp_path: Path) -> None:
    """物理坐标是个值：桶、载体、槽区间与长度一致即相等（便于比对与测试）。"""
    with _vault(tmp_path) as vault:
        place = vault.put(_record(b"payload"))
        assert place == Placement(
            bucket=place.bucket, pack=place.pack, span=place.span, size=place.size
        )
        assert place.span.end >= place.span.start
