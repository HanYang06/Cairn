# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""配置引擎：注册即事实，两个投影落盘，取值三条规则。

- 带值注册（``Cfg("k", 4096)``）→ ``config`` 与 ``schema`` 两侧都出现；
- 不带值（``Cfg("k")``）→ 只有 ``schema`` 出现，值丢了就报错（补不了）；
- key 在但值为空 → **报错**（不猜、不自动修）；
- 补只补缺失的键，**用户改过的值一个字都不动**。
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from core.conf import (
    ConfEngine,
    ConfigConflictError,
    ConfigFileError,
    ConfigKeyError,
    ConfigValueError,
    Folder,
)
from core.conf import conf as engine_conf
from core.conf.params import conf as kernel_conf
from core.conf.schema import type_schema
from core.storage import Bucket, BucketConfig, CarrierFile
from core.storage.conf import conf as storage_conf
from core.types import CairnError
from core.types.cfg import Cfg, clear, item, items, register

if TYPE_CHECKING:
    from collections.abc import Iterator

# 本文件之外的真声明（内核 / 存储那几组）：每例收尾要放回去，别让它被清掉。
_REAL_ITEMS = tuple(items())

_REAL = "core.demo.pack.max_blocks"
_VERSION = "core.demo.catalog.version"
_LEVEL = "core.demo.log.level"
_EMPTY_OK = "core.demo.pack.empty_ok"

# 从 Python 3.14 起，模块级注解的求值不再受 `from __future__` 影响。
_REAL_DEFAULT = 4096


def _declared_fields() -> dict[str, object]:
    """每次现造声明对象：描述符带 ``_resolved`` 缓存，跨用例复用会串味。"""
    return {
        "max_blocks": Cfg(_REAL, _REAL_DEFAULT, doc="单个载体最多装多少块"),
        "version": Cfg(_VERSION, doc="格式版本：只登记，不给值"),
        "level": Cfg(_LEVEL, "WARNING"),
        "empty_ok": Cfg(_EMPTY_OK, 7, empty_ok=True),
    }


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    """测试自己管登记表：跑完清干净，再**把真声明放回去**（别让别的用例失明）。"""
    yield
    clear()
    for declared_item in _REAL_ITEMS:
        register(declared_item)


@pytest.fixture
def declared() -> type:
    """每个用例重新声明一遍：登记表由用例清干净，声明得跟着重来。"""
    fields = _declared_fields()
    return type(
        "DemoCfg",
        (),
        {"__annotations__": dict.fromkeys(fields, Cfg), **fields},
    )


@pytest.fixture
def engine(tmp_path: Path) -> ConfEngine:
    """隔离的引擎：根在临时目录，不碰仓库里的真配置。"""
    return ConfEngine(tmp_path)


def _value_file(engine: ConfEngine) -> Path:
    """值文件：``config/<hub>/<包树>/<源文件名>.<type>``。"""
    return engine.root / "config" / engine.hub / "tests" / "core" / "test_conf.json"


def _schema_file(engine: ConfEngine) -> Path:
    """词表文件：与值文件同构（只换根目录、固定 ``.json``）。"""
    return engine.root / "schema" / engine.hub / "tests" / "core" / "test_conf.json"


def _write(engine: ConfEngine, data: dict[str, object]) -> None:
    path = _value_file(engine)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    engine.reload()


# ---- 两个投影 ----


@pytest.mark.usefixtures("declared")
def test_sync_writes_both_sides(engine: ConfEngine) -> None:
    """带值注册 → 两侧都有；不带值 → 只有词表有。"""
    engine.sync()
    assert _value_file(engine).is_file()
    assert _schema_file(engine).is_file()
    values = json.loads(_value_file(engine).read_text(encoding="utf-8"))
    schema = json.loads(_schema_file(engine).read_text(encoding="utf-8"))
    assert values[_REAL] == _REAL_DEFAULT
    assert _VERSION not in values  # 没默认值 → 值文件里不呈现
    assert _VERSION in schema["properties"]  # 但词表里承认它
    assert schema["properties"][_REAL]["type"] == "integer"
    assert schema["properties"][_REAL]["description"] == "单个载体最多装多少块"
    assert schema["properties"][_VERSION]["x-cairn-fillable"] is False


@pytest.mark.usefixtures("declared")
def test_value_file_points_at_its_schema(engine: ConfEngine) -> None:
    """值文件顶部的 ``$schema`` 指向对应词表（IDE 提示的入口）。"""
    engine.sync()
    values = json.loads(_value_file(engine).read_text(encoding="utf-8"))
    assert (
        values["$schema"].replace("\\", "/").endswith("schema/settings/tests/core/test_conf.json")
    )


@pytest.mark.usefixtures("declared")
def test_root_schema_collects_everything(engine: ConfEngine) -> None:
    engine.sync()
    root = json.loads(engine.index_path().read_text(encoding="utf-8"))
    assert _REAL in root["properties"]
    assert root["additionalProperties"] is False


# ---- 取值三条 ----


@pytest.mark.usefixtures("declared")
def test_get_returns_file_value_then_default(engine: ConfEngine) -> None:
    engine.sync()
    assert engine.get(_REAL) == _REAL_DEFAULT
    _write(engine, {_REAL: 512})
    assert engine.get(_REAL) == 512  # 文件说了算


@pytest.mark.usefixtures("declared")
def test_missing_key_with_default_is_refilled(engine: ConfEngine) -> None:
    """key 丢了但有默认值 → 补回来（文件删了也能重展开）。"""
    engine.sync()
    _write(engine, {})
    assert engine.get(_REAL) == _REAL_DEFAULT
    values = json.loads(_value_file(engine).read_text(encoding="utf-8"))
    assert values[_REAL] == _REAL_DEFAULT  # 真写回文件了


@pytest.mark.usefixtures("declared")
def test_missing_key_without_default_raises(engine: ConfEngine) -> None:
    """key 丢了且没默认值 → 报错（补不了）。"""
    engine.sync()
    with pytest.raises(ConfigKeyError, match="没有默认值"):
        engine.get(_VERSION)


@pytest.mark.usefixtures("declared")
def test_empty_value_raises(engine: ConfEngine) -> None:
    """key 在、值空 → 报错，不自动修。"""
    engine.sync()
    _write(engine, {_REAL: None})
    with pytest.raises(ConfigValueError, match="值为空"):
        engine.get(_REAL)


@pytest.mark.usefixtures("declared")
def test_empty_ok_treats_empty_as_default(engine: ConfEngine) -> None:
    """``empty_ok=True``（增强写法）：空值也按默认处理。"""
    engine.sync()
    for blank in (None, "", []):
        _write(engine, {_EMPTY_OK: blank})
        assert engine.get(_EMPTY_OK) == 7


# ---- 写与维护 ----


@pytest.mark.usefixtures("declared")
def test_user_value_is_never_overwritten(engine: ConfEngine) -> None:
    """补只补缺失的键；用户改过的值一个字都不动。"""
    engine.sync()
    engine.set(_REAL, 128)
    engine.sync()
    engine.sync()
    assert engine.get(_REAL) == 128


@pytest.mark.usefixtures("declared")
def test_set_unknown_key_raises(engine: ConfEngine) -> None:
    engine.sync()
    with pytest.raises(ConfigKeyError, match="未登记"):
        engine.set("core.demo.nope", 1)


def test_attribute_access_reports_engine_state(
    engine: ConfEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """属性访问 = 引擎的判据：引擎说读到什么，属性就给什么。

    真值路径由 `test_get_returns_file_value_then_default` 等用例覆盖；这里只钉住
    "描述符确实把判据交给引擎"——把引擎换成隔离的那份，写什么就读到什么。
    """
    monkeypatch.setattr("core.conf.engine.conf", engine)
    holder = type(
        "Holder",
        (),
        {"__annotations__": {"max_blocks": Cfg}, "max_blocks": Cfg(_REAL, _REAL_DEFAULT)},
    )
    engine.set(_REAL, 64)
    assert holder.max_blocks == 64
    engine.set(_REAL, _REAL_DEFAULT)
    assert holder.max_blocks == _REAL_DEFAULT


@pytest.mark.usefixtures("declared")
def test_sync_is_idempotent(engine: ConfEngine) -> None:
    """同步是投影：重复跑不产生新文件、不改内容、第二次不再写。"""
    first = sorted(path for path, _touched in engine.sync())
    before = {path: path.read_bytes() for path in first}
    second = sorted(path for path, _touched in engine.sync())
    after = {path: path.read_bytes() for path in second}
    assert first == second
    assert before == after
    assert all(not touched for _path, touched in engine.sync())


@pytest.mark.usefixtures("declared")
def test_broken_file_raises(engine: ConfEngine) -> None:
    engine.sync()
    _value_file(engine).write_text("{ 不是 json", encoding="utf-8")
    engine.reload()
    with pytest.raises(ConfigFileError, match="不可读"):
        engine.get(_REAL)


# ---- 重名检查（不覆盖别人的文件） ----


@pytest.mark.usefixtures("declared")
def test_foreign_file_is_refused_not_overwritten(engine: ConfEngine) -> None:
    """值文件位置上压着一份别人的文件（无 ``$schema``、也没有我们的键）→ 拒写。"""
    path = _value_file(engine)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"别人的键": 1}', encoding="utf-8")
    engine.reload()
    found = engine.conflicts()
    assert any("重名" not in line and str(path) in line for line in found)
    with pytest.raises(ConfigConflictError, match="重名"):
        engine.sync()
    assert json.loads(path.read_text(encoding="utf-8")) == {"别人的键": 1}  # 一个字没动


@pytest.mark.usefixtures("declared")
def test_file_pointing_elsewhere_is_refused(engine: ConfEngine) -> None:
    """值文件带着指向**别处**的 ``$schema`` → 拒写（那是别人的词表）。"""
    path = _value_file(engine)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"$schema": "../../schema/other.json"}', encoding="utf-8")
    engine.reload()
    assert any("$schema 指向别处" in line for line in engine.conflicts())
    with pytest.raises(ConfigConflictError):
        engine.sync()


def test_repo_projections_match_declarations() -> None:
    """端到端：仓库里已提交的投影与声明一致（`gen_conf.py --check` 的等价断言）。"""
    root = Path(__file__).resolve().parents[2]
    command = [sys.executable, str(root / "tools" / "gen_conf.py"), "--check"]
    done = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",  # 工具按 UTF-8 打印中文；别让子进程按活动代码页解码
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr


# ---- 接线：声明的默认值真的生效 ----


def test_bucket_config_defaults_come_from_declarations() -> None:
    """桶配置的默认值来自存储自己的声明（不是写死在 `BucketConfig` 里）。"""
    resolved = BucketConfig()
    assert resolved.block_max_bytes == storage_conf.block_max_bytes
    assert resolved.pack_max_bytes == storage_conf.pack_max_bytes


def test_config_file_drives_bucket_config(tmp_path: Path) -> None:
    """改配置文件 → 桶跟着变（**文件说了算**），改完还原。"""
    original = engine_conf.get("storage.pack.max_bytes")
    try:
        engine_conf.set("storage.pack.max_bytes", 4096)
        assert BucketConfig().pack_max_bytes == 4096
        bucket = Bucket.create(tmp_path / "bucket")
        assert bucket.config.pack_max_bytes == 4096
    finally:
        engine_conf.set("storage.pack.max_bytes", original)


def test_carrier_slot_bytes_default_comes_from_declaration(tmp_path: Path) -> None:
    """建载体时槽长向声明要；**读回时从文件头读**，不再问配置。"""
    declared = storage_conf.pack_slot_bytes
    carrier = CarrierFile.create(tmp_path / "pack")
    assert carrier.layout.slot_bytes == declared
    original = engine_conf.get("storage.pack.slot_bytes")
    try:
        engine_conf.set("storage.pack.slot_bytes", declared * 2)
        # 已建载体不被新配置改写：仍按自己文件头里的槽长解释
        assert CarrierFile.open(tmp_path / "pack").layout.slot_bytes == declared
    finally:
        engine_conf.set("storage.pack.slot_bytes", original)


def test_bucket_config_rejects_non_integer_value() -> None:
    """值文件里的整数项被改成字符串 → 在配置边界报清楚，不在分片关键路径上抛 `TypeError`。"""
    original = engine_conf.get("storage.block.max_bytes")
    try:
        engine_conf.set("storage.block.max_bytes", "1048576")
        with pytest.raises(CairnError, match="必须是正整数"):
            BucketConfig()
    finally:
        engine_conf.set("storage.block.max_bytes", original)


def test_kernel_log_level_is_applied() -> None:
    """`core.log.level` 真接到 `core.*` 这族 logger 上。"""
    assert logging.getLogger("core").level == logging.getLevelName(kernel_conf.log_level)


# ---- 评审回归：投影坐标 / 计划去重 / 坏文件判定 / 描述符边界 ----


def test_folder_of_path_matches_folder_of() -> None:
    """由配置路径反推的 `Folder` 必须与由模块名建的那个**相等**。

    `Folder` 是 frozen dataclass，`source` 参与相等性与哈希——差一层目录
    （`src/core/core/storage/conf`）会让「按路径找回声明」静默失配，重名检查随之退化。
    """
    assert Folder.of_path(Path("core/storage/conf.json")) == Folder.of("core.storage.conf")
    assert Folder.of_path(Path("core/storage/conf.json")).source == Path("src/core/storage/conf")


@pytest.mark.usefixtures("declared")
def test_plan_lists_each_projection_once(engine: ConfEngine) -> None:
    """每份投影只入队一次：总词表若放在按 folder 的循环里，会被重复追加与重复写入。"""
    paths = [path for path, _body, _stale in engine.plan()]

    assert len(paths) == len(set(paths))
    assert paths.count(engine.index_path()) == 1


@pytest.mark.usefixtures("declared")
def test_broken_value_file_raises_file_error_in_conflicts(engine: ConfEngine) -> None:
    """config 侧读到坏文件 → `ConfigFileError`（「文件坏了」比「像不像自己人」更准）。"""
    engine.sync()
    _value_file(engine).write_text("{ 不是 json", encoding="utf-8")
    engine.reload()

    with pytest.raises(ConfigFileError, match="不可读"):
        engine.conflicts()


@pytest.mark.usefixtures("declared")
def test_conflicts_reports_every_problem_at_once(engine: ConfEngine) -> None:
    """坏文件与重名同时存在时，异常信息里两者都要有（先收集、末尾统一抛）。

    计划直接构造为「已过期」，模拟「算计划时还好、写盘时已坏」的时序：
    中途 `raise` 会把这一轮已经查到的重名项一起丢掉。
    """
    value, schema = _value_file(engine), _schema_file(engine)
    value.parent.mkdir(parents=True, exist_ok=True)
    schema.parent.mkdir(parents=True, exist_ok=True)
    plans = [(value, {"$schema": "x"}, True), (schema, {"$schema": "y"}, True)]
    value.write_text("{ 也不是 json", encoding="utf-8")
    schema.write_text("{ 不是 json", encoding="utf-8")

    with pytest.raises(ConfigFileError, match="另有 1 处重名"):
        engine.conflicts(plans)


@pytest.mark.usefixtures("declared")
def test_set_refuses_to_overwrite_a_foreign_file(engine: ConfEngine) -> None:
    """单值写也不得覆盖别人的文件：`set()` 与 `sync()` 同一口径（整份重写同样危险）。"""
    path = _value_file(engine)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"别人的键": 1}', encoding="utf-8")
    engine.reload()

    with pytest.raises(ConfigConflictError, match="重名"):
        engine.set(_REAL, 5)

    assert json.loads(path.read_text(encoding="utf-8")) == {"别人的键": 1}  # 一个字没动


@pytest.mark.usefixtures("declared")
def test_repair_refuses_to_adopt_a_foreign_file(engine: ConfEngine) -> None:
    """补缺失键（`_repair`）同样不得把别人的文件据为己有，也不得注入自己的 `$schema`。"""
    path = _value_file(engine)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"别人的键": 1}', encoding="utf-8")
    engine.reload()

    with pytest.raises(ConfigConflictError, match="重名"):
        engine.get(_REAL)

    assert json.loads(path.read_text(encoding="utf-8")) == {"别人的键": 1}


@pytest.mark.usefixtures("declared")
def test_runtime_write_does_not_drift_from_the_plan(engine: ConfEngine) -> None:
    """运行期写值之后文件必须与 `plan()` 的期望逐字节一致（键序也要一致）。

    `gen_conf.py --check` 按文本比较：写值若另排一种键序，配置会被误报成漂移。
    """
    engine.sync()
    path = _value_file(engine)
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({"zz.user": 1, **data}, ensure_ascii=False), encoding="utf-8")
    engine.reload()

    engine.set(_REAL, 128)

    assert all(not stale for _path, _payload, stale in engine.plan())


def test_annotated_item_type_wins_over_the_default() -> None:
    """文档推荐的 `Cfg[int]` 写法必须真的生效（下标即注解里的类型，不退化成按默认值推）。"""
    field = Cfg("core.demo.typed.size", "默认值是字符串")
    holder = type("TypedCfg", (), {"__annotations__": {"size": Cfg[int]}, "size": field})

    assert holder is not None
    declared = item("core.demo.typed.size")
    assert declared is not None
    assert declared.type is int
    assert declared.default == "默认值是字符串"


def test_none_default_is_rejected_unless_empty_ok() -> None:
    """空默认值（`None` / 空串 / 空容器）都会写出读不回来的配置 → 声明期即拒绝。"""
    for blank in (None, "", [], {}, ()):
        with pytest.raises(ValueError, match="默认值不得为空"):
            Cfg("core.demo.pack.none_default", blank)

    allowed = Cfg("core.demo.pack.none_default", None, empty_ok=True)
    assert allowed.default is None


def test_zero_and_false_are_not_empty_defaults() -> None:
    """`0` 与 `False` 不算空值（与引擎的空值口径一致），可以正常带值注册。"""
    assert Cfg("core.demo.pack.zero", 0).default == 0

    disabled = False
    assert Cfg("core.demo.pack.off", disabled).default is disabled


def test_union_annotation_reaches_the_schema() -> None:
    """`Cfg[int | None]` 必须被采纳：按「必须是 type」筛掉会让显式声明被无声吞掉。"""
    field = Cfg("core.demo.typed.optional", 0)
    holder = type(
        "OptionalCfg",
        (),
        {"__annotations__": {"optional": Cfg[int | None]}, "optional": field},
    )

    assert holder is not None
    declared = item("core.demo.typed.optional")
    assert declared is not None
    assert declared.type == int | None
    assert type_schema(declared.type) == {"anyOf": [{"type": "integer"}, {"type": "null"}]}


def test_type_schema_does_not_narrow_a_union() -> None:
    """联合里有认不出的分支时整体不给约束——只留认得的那支会给出过窄的错约束。"""

    class Custom:
        """词表不认的自定义类型。"""

    assert type_schema(int | Custom) == {}
    assert type_schema(str | int) == {"anyOf": [{"type": "string"}, {"type": "integer"}]}
    assert type_schema(Custom) == {}


def test_type_schema_handles_parameterised_generics() -> None:
    """`list[int]` / `dict[str, int]` 这类泛型提示要认：声明采纳了它们，词表不得静默丢掉。"""
    assert type_schema(list[int]) == {"type": "array", "items": {"type": "integer"}}
    assert type_schema(list) == {"type": "array", "items": {}}
    assert type_schema(dict[str, int]) == {"type": "object"}
    assert type_schema(list[object]) == {"type": "array", "items": {}}


@pytest.mark.usefixtures("declared")
def test_sync_leaves_no_temporary_files(engine: ConfEngine) -> None:
    """投影走「临时文件 + 改名」的原子写：写完不得留下 `.tmp` 残渣。"""
    for path, _touched in engine.sync():
        assert not path.with_name(f"{path.name}.tmp").exists()


def test_caller_default_is_not_cached(engine: ConfEngine) -> None:
    """未登记键的「调用方 default」不进缓存：同一个 key 换一个 default 必须给新值。"""
    assert engine.get("core.demo.unknown", 5) == 5
    assert engine.get("core.demo.unknown", 9) == 9


def test_blank_docstring_does_not_break_registration() -> None:
    """类 docstring 是空白串时不得在类体定义期抛 `IndexError`（登记仍要完成）。"""
    field = Cfg("core.demo.blank.doc", 1)
    holder = type("BlankDoc", (), {"__doc__": "   ", "value": field})

    assert holder is not None
    assert item("core.demo.blank.doc") is not None
