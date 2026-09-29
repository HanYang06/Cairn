# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""配置引擎契约：一种调用形（声明 / 取值）、引擎自组批次、单向写入、类型判据、单文件投影。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.conf import Config
from core.conf.types import check_type, spec_of
from core.exc import (
    ConfigDuplicateError,
    ConfigFileError,
    ConfigKeyError,
    ConfigReferenceError,
    ConfigTypeError,
)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """一个空的配置根：值文件与词表都落在它下面。"""
    return tmp_path / "config"


@pytest.fixture
def conf(root: Path) -> Config:
    """一份独立的配置面（不碰进程级那个 `conf`，免得用例互相污染）。"""
    return Config(root=root)


def values(conf: Config) -> dict[str, object]:
    """读回值文件里的键与值（去掉开头的 `$schema` 那一行）。"""
    data: dict[str, object] = json.loads(conf.settings_path().read_text(encoding="utf-8"))
    data.pop("$schema", None)
    return data


# ---- 一种调用形：声明与取值 ---- #


def test_declare_then_read_back(conf: Config):
    """声明即拿到默认值；同一形状的取值拿到同一个值。"""
    assert conf("storage.pack.slot_bytes", 65536, type=int) == 65536
    assert conf("storage.pack.slot_bytes") == 65536


def test_declaration_without_default_is_read_only(conf: Config):
    """只给 `type` / `doc` 是在声明"没有默认值"的项：不补进文件，读不到就报错。"""
    conf("core.mode", type=str, doc="运行模式")

    with pytest.raises(ConfigKeyError):
        conf("core.mode")
    assert conf.plan() == ()


def test_reading_an_undeclared_key_is_an_error(conf: Config):
    """没声明的键读不出来：不猜、不自动造。"""
    with pytest.raises(ConfigKeyError):
        conf("nobody.knows")


def test_values_of_every_json_type(conf: Config):
    """六种 JSON 值各走一遍：写出去、读回来、类型不变。"""
    conf("a.int", 1)
    conf("a.float", 1.5)
    conf("a.bool", True)
    conf("a.str", "文字")
    conf("a.list", [1, 2], type=list[int])
    conf("a.dict", {"k": "v"}, type=dict[str, str])
    conf("a.null", None)
    conf.sync()

    assert conf("a.int") == 1
    assert conf("a.float") == 1.5
    assert conf("a.bool") is True
    assert conf("a.str") == "文字"
    assert conf("a.list") == [1, 2]
    assert conf("a.dict") == {"k": "v"}
    assert conf("a.null") is None


def test_pending_value_is_visible_before_flush(conf: Config):
    """写了立刻读必须拿到刚写的值：批内可见，不然用法自相矛盾。"""
    conf("a.b", 1)

    assert conf("a.b") == 1
    assert not conf.settings_path().exists()


# ---- 批：写只记一笔，落盘一次 ---- #


def test_dense_writes_flush_once(conf: Config):
    """密集调用只落一次盘：默认通路不即时，`sync()` 才写文件。"""
    for index in range(20):
        conf(f"a.k{index}", index)

    assert not conf.settings_path().exists()
    result = conf.sync()
    assert len(result.added) == 20
    assert len(values(conf)) == 20


def test_sync_is_idempotent_and_does_not_touch_an_unchanged_file(conf: Config):
    """第二次落盘没有内容变化：不重写文件（时间戳也不动）。"""
    conf("a.b", 1)
    conf.sync()
    stamp = conf.settings_path().stat().st_mtime_ns

    result = conf.sync()

    assert result.added == ()
    assert result.changed == ()
    assert conf.settings_path().stat().st_mtime_ns == stamp


def test_plan_reports_only_real_changes(conf: Config):
    """`plan()` 按内容判：写进文件之后就没有待落盘的变化了。"""
    conf("a.b", 1)
    assert conf.plan() == ("a.b",)

    conf.sync()
    assert conf.plan() == ()


def test_sync_drops_keys_the_declaration_no_longer_mentions(conf: Config, root: Path):
    """曾声明、后已删除的键随落盘消失（它既不在登记表里，也不是用户加的）。"""
    root.mkdir(parents=True)
    conf.settings_path().write_text(
        json.dumps({"$schema": "schema/settings.json", "old.key": 1}) + "\n", encoding="utf-8"
    )
    fresh = Config(root=root)
    fresh.reduce({"old.key": "core.somewhere"})

    fresh.sync()

    assert values(fresh) == {}


# ---- 写入方向：代码 → 文件，单向 ---- #


def test_second_assignment_in_code_is_refused(conf: Config):
    """同一键再赋值即报错，报错里带上先声明那一处（模块 + 文件 + 行号）。"""
    conf("a.b", 1)

    with pytest.raises(ConfigDuplicateError) as caught:
        conf("a.b", 2)

    assert "test_conf.py" in str(caught.value)


def test_duplicate_inside_one_batch_is_refused(conf: Config):
    """一批里写两次同一个键同样报错：判据含待写项，不看落盘了没有。"""
    conf("a.b", 1)

    with pytest.raises(ConfigDuplicateError):
        conf("a.b", 2)


def test_value_in_the_file_does_not_block_a_declaration(conf: Config, root: Path):
    """文件里有这个键不构成"不许再声明"：删了值文件的键之后再补回来是常态。

    "已经有值"的判据是**本会话声明过**，不是"文件里有这一行"——否则补写会被自己的口径挡住。
    """
    conf.settings_path().parent.mkdir(parents=True, exist_ok=True)
    conf.settings_path().write_text(
        json.dumps({"$schema": "schema/settings.json", "a.b": 99}) + "\n", encoding="utf-8"
    )
    fresh = Config(root=root)

    assert fresh("a.b", 1) == 1
    assert fresh("a.b") == 1


def test_redeclaring_in_the_same_session_is_refused_by_the_ledger(conf: Config):
    """同一会话里第二次声明同一个键：登记账说了算，与文件里有没有无关。"""
    conf("a.b", 1)

    with pytest.raises(ConfigDuplicateError):
        conf("a.b", 1)


def test_force_overwrites(conf: Config):
    """强写：`force=True` 是唯一能顶掉已有值的通路。"""
    conf("a.b", 1)

    assert conf("a.b", 2, force=True) == 2
    assert conf("a.b") == 2
    conf.sync()
    assert values(conf)["a.b"] == 2


def test_force_still_checks_type(conf: Config):
    """强写只放开"能不能改"，不放开类型判据。"""
    conf("a.b", 1, type=int)

    with pytest.raises(ConfigTypeError):
        conf("a.b", 1.5, force=True)


# ---- 用户手改的文件 ----


def test_user_edited_value_wins_and_is_not_overwritten(conf: Config, root: Path):
    """用户改过的值永不被覆写：代码手里的默认值顶不掉文件里的改动。"""
    conf("a.b", 1)
    conf.sync()
    data = values(conf)
    data["a.b"] = 4096
    conf.settings_path().write_text(json.dumps(data) + "\n", encoding="utf-8")

    fresh = Config(root=root)
    assert fresh("a.b") == 4096
    assert fresh.plan() == ()
    fresh.sync()
    assert values(fresh)["a.b"] == 4096


def test_user_added_keys_are_kept(conf: Config, root: Path):
    """用户自己加的键留着：引擎只补缺失的键、不删不改别人的东西。"""
    conf("a.b", 1)
    conf.sync()
    data = values(conf)
    data["user.mine"] = {"hello": "world"}
    conf.settings_path().write_text(json.dumps(data) + "\n", encoding="utf-8")

    fresh = Config(root=root)
    assert fresh("user.mine") == {"hello": "world"}
    fresh.sync()
    assert values(fresh)["user.mine"] == {"hello": "world"}


def test_missing_default_is_filled_back(conf: Config, root: Path):
    """文件里少了带默认值的键：模块一跑（声明一次）就补回来。"""
    conf("a.b", 7)
    conf.sync()
    conf.settings_path().write_text(json.dumps({"$schema": "schema/settings.json"}) + "\n")

    fresh = Config(root=root)
    assert fresh("a.b", 7) == 7
    fresh.sync()

    assert values(fresh) == {"a.b": 7}


# ---- 类型判据 ---- #


@pytest.mark.parametrize(
    ("value", "declared", "expected"),
    [
        (1, float, 1.0),
        (1.5, float, 1.5),
        (True, bool, True),
        ("x", str, "x"),
        (None, type(None), None),
    ],
)
def test_type_rules_that_pass(conf: Config, value: object, declared: object, expected: object):
    """判据放行的几种：整数在浮点键上按浮点算，其余要求类型同一。"""
    conf("a.b", value, type=declared)

    assert conf("a.b") == expected
    assert conf("a.b") is not True or expected is True


@pytest.mark.parametrize("bad", [1.5, "x", None, True])
def test_int_key_refuses_everything_but_int(conf: Config, bad: object):
    """`type=int` 只收整数：浮点、字符串、空值、布尔一律拦下（`True` 也不放行）。"""
    with pytest.raises(ConfigTypeError):
        conf("a.b", bad, type=int)


def test_bool_does_not_masquerade_as_int(conf: Config):
    """`isinstance(True, int)` 为真，但 `type=int` 配 `True` 必须拦下。"""
    with pytest.raises(ConfigTypeError):
        conf("a.b", True, type=int)


def test_widening_writes_a_float(conf: Config):
    """整数默认值在浮点键上按浮点写出：否则读回变整数，会自己把自己拦下。"""
    conf("a.b", 65536, type=float)
    conf.sync()

    assert values(conf)["a.b"] == 65536.0
    assert isinstance(values(conf)["a.b"], float)


def test_type_is_inferred_from_the_default(conf: Config):
    """省略 `type` 时按默认值自身的类型判。"""
    conf("a.b", "文字")

    assert conf("a.b") == "文字"


@pytest.mark.parametrize("bad_type", [bytes, set, tuple, object])
def test_unsupported_types_are_refused_at_declaration(conf: Config, bad_type: object):
    """落不成 JSON 的类型在声明期就拒，而不是等落盘时崩。"""
    with pytest.raises(ConfigTypeError):
        conf("a.b", 1, type=bad_type)


def test_containers_take_one_level_of_element(conf: Config):
    """容器类型可以带一层元素，非法元素当场拦下。"""
    conf("a.list", [1, 2], type=list[int])
    conf("a.dict", {"k": 1}, type=dict[str, int])
    conf.sync()

    assert conf("a.list") == [1, 2]
    assert conf("a.dict") == {"k": 1}

    with pytest.raises(ConfigTypeError):
        conf("a.bad", [1], type=list[str])


def test_hand_edited_type_mismatch_is_refused_on_read(conf: Config, root: Path):
    """人手把值改成别的类型：下一个进程一声明它就当场报错，不静默当另一个类型用。"""
    conf.settings_path().parent.mkdir(parents=True, exist_ok=True)
    conf.settings_path().write_text(
        json.dumps({"$schema": "schema/settings.json", "a.b": "文字"}) + "\n", encoding="utf-8"
    )
    fresh = Config(root=root)

    with pytest.raises(ConfigTypeError):
        fresh("a.b", 1, type=int)


def test_non_json_default_is_refused(conf: Config):
    """默认值本身落不成 JSON（如 `Path`）同样在声明期拒。"""
    with pytest.raises(ConfigTypeError):
        conf("a.b", Path("x"))


# ---- 坏文件 ---- #


def test_broken_json_is_an_error(conf: Config):
    """值文件读不成 JSON：报错，不猜也不重写。"""
    conf.settings_path().parent.mkdir(parents=True, exist_ok=True)
    conf.settings_path().write_text("{ not json", encoding="utf-8")

    with pytest.raises(ConfigFileError):
        conf("a.b")


def test_root_must_be_an_object(conf: Config):
    """值文件的根不是对象：报错。"""
    conf.settings_path().parent.mkdir(parents=True, exist_ok=True)
    conf.settings_path().write_text("[1, 2]\n", encoding="utf-8")

    with pytest.raises(ConfigFileError):
        conf("a.b")


# ---- 文件引用 ---- #


def test_file_reference_resolves_next_to_the_value_file(conf: Config):
    """`file="yaml"` 默认指向同层级的 `<字段名>.yaml`，值文件里那一行是引用名。"""
    conf.settings_path().parent.mkdir(parents=True, exist_ok=True)
    (conf.settings_path().parent / "tables.yaml").write_text("- name: x\n", encoding="utf-8")

    conf("storage.db.tables", "", type=str, file="yaml")
    conf.sync()

    assert values(conf)["storage.db.tables"] == "tables.yaml"


def test_file_reference_must_exist(conf: Config):
    """被引用的文件不在：声明期就报错，本体要放好。"""
    with pytest.raises(ConfigReferenceError):
        conf("storage.db.tables", "", type=str, file="yaml")


def test_file_reference_may_not_escape_the_root(conf: Config):
    """引用名不许跑出仓根。"""
    with pytest.raises(ConfigReferenceError):
        conf("storage.db.tables", "../../etc/passwd", type=str, file="yaml")


# ---- 路径与装配 ---- #


def test_value_file_points_at_the_schema(conf: Config):
    """值文件顶部那句 `$schema` 指向词表（相对路径，搬仓不失效）。"""
    conf("a.b", 1)
    conf.sync()

    head = json.loads(conf.settings_path().read_text(encoding="utf-8"))["$schema"]
    assert head == "schema/settings.json"
    assert conf.schema_path().is_file()


def test_schema_carries_type_default_and_owner(conf: Config):
    """词表带类型、默认值、说明、出处：IDE 悬停与文档页都吃它。"""
    conf("a.b", 1, type=int, doc="说明")
    conf.sync()

    properties = json.loads(conf.schema_path().read_text(encoding="utf-8"))["properties"]
    assert properties["a.b"]["type"] == "integer"
    assert properties["a.b"]["default"] == 1
    assert properties["a.b"]["description"] == "说明"
    assert properties["a.b"]["x-cairn-owner"].startswith("test_conf.")
    assert "tests/core/test_conf.py:" in properties["a.b"]["x-cairn-site"]


def test_config_root_follows_the_environment_knob(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """`CAIRN_CONFIG` 是找到配置的办法（测试与部署用），不是配置项。"""
    monkeypatch.setenv("CAIRN_CONFIG", str(tmp_path / "elsewhere"))
    conf = Config()

    assert conf.config_root() == tmp_path / "elsewhere"

    conf.use(tmp_path / "here")
    assert conf.config_root() == tmp_path / "here"
    assert os.environ["CAIRN_CONFIG"] == str(tmp_path / "elsewhere")


def test_reduce_registers_declarations_without_running_them(conf: Config):
    """扫描那条路：按清单登记，不执行模块；本处没声明的键读不到。"""
    assert conf.reduce({"a.b": "core.somewhere", "c.d": "core.elsewhere"}) == ("a.b", "c.d")
    assert conf.used() == frozenset()

    with pytest.raises(ConfigKeyError):
        conf("a.b")


def test_reduce_does_not_shadow_a_real_declaration(conf: Config):
    """本处声明过的键，扫描登记不覆盖它。"""
    conf("a.b", 1)

    assert conf.reduce({"a.b": "core.somewhere"}) == ()
    assert conf("a.b") == 1


# ---- 判据函数本身 ---- #


@pytest.mark.parametrize(
    ("type_arg", "value"),
    [
        (int, 1),
        (float, 1.5),
        (bool, False),
        (str, "x"),
        (list[int], [1]),
        (dict[str, int], {"a": 1}),
        (None, None),
        (int | None, 3),
    ],
)
def test_spec_and_check_round_trip(type_arg: object, value: object):
    """`spec_of` 收下的写法，`check_type` 都判得过。"""
    assert check_type(value, spec_of(type_arg)) == value
