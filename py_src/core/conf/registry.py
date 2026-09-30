# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""配置引擎：一个 `conf` 面、一层待写批、一份单文件投影。

这个包只做"配置"这一件事，形状是四个东西：**一个 `conf` 面、一个待写字典、一个 JSON 文件、
一个退出时的刷盘钩子**。没有 `get` / `set` 第二套动词，没有批次栈——声明与取值是同一个调用形，
差别只在给不给参数：

    conf("storage.pack.slot_bytes", 65536, type=int, doc="槽长")  # 声明
    slot = conf("storage.pack.slot_bytes")                        # 取值

**事务由引擎自己组织，调用方不划批次**。写侧只记一笔待写、立即返回；到该落盘的时刻
（进程退出、或显式 `sync()` / `force=True`）才做完整轮：读旧值 → 补缺失键 → 一次写盘
→ 词表重算一次。之所以能不划批次，是因为这一层的写操作**幂等且无序**（只补缺失、不改已写），
任何一批的子集、超集、重排落盘结果都合法——批次因此只是减少 IO 的优化，不是语义边界。

**写入方向只有一个：代码 → 文件**。改值只能从配置文件改回来，除非显式 `force=True`。
于是重复声明在启动时就炸（报错带上先声明那一处的出处），用户手改的值也天然不会被代码顶掉。

注意事项（影响都不大，故只写在这里）：

- **默认不即时**：`conf(k, v)` 只记一笔，崩溃丢的是"还没落盘的那几笔"。这不是数据事故——
  声明写死在代码里、已落盘的值一个字节没动，重启即可恢复；文件永远不含错东西，
  只会比预期旧一个版本。
- **只读盘写不出去不报错**：值文件是投影，写不出去不影响本次运行；读值也不依赖"先写成功"。
- **值文件缺失 / 陈旧不是错误**：缺了按声明重建，旧了只补缺失的键。
"""

from __future__ import annotations

import atexit
import contextlib
import inspect
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, TypeVar, cast, overload

from core.conf import schema
from core.conf.types import MISSING, JsonValue, TypeSpec, check_type, spec_of
from core.exc import (
    ConfigDuplicateError,
    ConfigFileError,
    ConfigKeyError,
    ConfigReferenceError,
    ConfigTypeError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

LOGGER = logging.getLogger("cairn.conf")

#: 配置根：值文件与词表都落在这里（`config/` 下）
CONFIG_DIRNAME = "config"

#: 值文件与词表的名字（单文件投影：一个 hub 一份）
VALUE_FILENAME = "settings.json"
SCHEMA_DIRNAME = "schema"

#: 值文件里那一行的键名（指向词表；不算配置项本身）
SCHEMA_KEY = "$schema"

#: 环境旋钮：只给测试与部署重定向，**不进配置**（它不是配置项，是找到配置的办法）
ROOT_ENV = "CAIRN_CONFIG"

#: 文件引用的类型名 → 扩展名（`file="yaml"` → `tables.yaml`）
FILE_TYPES: dict[str, str] = {"yaml": "yaml", "json": "json"}

_T = TypeVar("_T")
_CALLER_DEPTH = 3
"""从 `_call_site` 往上数几层才到调用方：`__call__` → `_assign` → 调用方。"""

_REDUCE_CALLER_DEPTH = 2
"""`reduce()` 那条链路的层数：`reduce` 只隔一层，不像 `__call__` 那样先经 `_assign`。"""


@dataclass(frozen=True, slots=True)
class CallSite:
    """一处调用点的出处：模块名 + 文件相对路径 + 行号（+ 所在函数 / 类名）。

    作用是让"重复声明"这类报错指得出**先声明那一处**在哪，否则只知道撞了、不知道撞了谁。
    """

    module: str
    file: str
    line: int
    qualname: str = "?"

    def __str__(self) -> str:
        """`模块名（相对路径:行号）`：报错里直接内插它即可。"""
        return f"{self.module}（{self.file}:{self.line}）"


@dataclass(frozen=True, slots=True)
class _Item:
    """一条声明：规范化类型、默认值（可能没有）、说明、出处，以及归属（词表用）。"""

    spec: TypeSpec
    default: object
    doc: str
    site: CallSite
    module: str = "?"
    qualname: str = "?"


@dataclass(frozen=True, slots=True)
class _Options:
    """一次声明的副参数（类型、说明、文件引用、强写）：打成一包，免得签名一路加参数。

    `declare_type` 这个字段名与调用面用的 `type` 不同：调用面要跟作者的写法一致（`type=`），
    这里避开同名，免得包内到处遮蔽内置的 `type`。
    """

    declare_type: object = MISSING
    doc: str = ""
    file: str | None = None
    force: bool = False


class Declared(NamedTuple):
    """一条登记项：键 + 声明 + 它是从哪一行写出来的（词表投影按它渲染）。"""

    path: str
    item: _Item
    module: str
    qualname: str
    site: CallSite


class SyncResult(NamedTuple):
    """一次落盘的结果：新增的键、改动的键，以及两份产物的路径。"""

    added: tuple[str, ...]
    changed: tuple[str, ...]
    value_path: Path
    schema_path: Path


class Config:
    """配置面：一个可调用的对象，管着登记表、待写批与那份单文件投影。

    通常不必自己造：模块级的 `conf` 就是它（见 `core/conf/__init__.py`）。
    自己造一个的场合只有"要另指一个配置根"（测试、或嵌入式部署）：

        conf = Config(root=tmp_path)

    参数：

    - `root`：配置根目录；不给则按环境旋钮 `CAIRN_CONFIG`、再退到仓根下的 `config/`。
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root
        self._loaded: dict[str, JsonValue] | None = None
        self._session: dict[str, JsonValue] = {}
        self._declarations: dict[str, _Item] = {}
        self._elsewhere: dict[str, _Item] = {}
        self._pending: dict[str, JsonValue | None] = {}
        self._seen: set[str] = set()

    # ---- 调用面：声明 / 取值 ---- #

    @overload
    def __call__(
        self,
        path: str,
        default: _T,
        *,
        type: object = ...,
        doc: str = ...,
        file: str | None = ...,
        force: bool = ...,
    ) -> _T: ...

    @overload
    def __call__(self, path: str, *, type: object = ..., doc: str = ...) -> Any: ...

    def __call__(
        self,
        path: str,
        default: Any = MISSING,
        *,
        type: object = MISSING,
        doc: str = "",
        file: str | None = None,
        force: bool = False,
    ) -> Any:
        """声明一个配置项，或读取一个已声明的配置项。

        参数：

        - `path`：点分键（`storage.pack.slot_bytes`）；同时是值文件里的属性名，不展开成嵌套对象；
        - `default`：默认值。**不给就是只读**——除非同时给了 `type` / `doc` / `file`，
          那是在声明一个"没有默认值"的项（那种键的值必须由文件给，丢了即报错）；
        - `type`：这条键的类型（`int` / `float` / `bool` / `str` / `list[int]` / `dict[str, int]`
          / `None`）。省略时按默认值自身的类型判；
        - `doc`：写进词表的说明（IDE 悬停能看到）；
        - `file`：这一项的值放进独立文件（`"yaml"` → 同层级的 `tables.yaml`）；
          值文件里那一行是引用名，本体在被引用的那份文件里；
        - `force`：强写。**代码 → 文件是单向的**，改值只能从配置文件改回来，
          除非显式开它（"这一笔就是要改、谁也拦不住"）。

        Returns:
            声明的默认值（声明时），或这一条键当前的值（取值时）。

        Raises:
            ConfigTypeError: 声明的类型不是允许的写法，或类型与默认值不符；
                读回来的值与该键声明的类型不符时同样抛它。
            ConfigDuplicateError: 这个键已经有值（文件里、或本会话已声明过）而代码又给它赋值。
            ConfigKeyError: 键没有值可读——它不在值文件里，声明处也没有默认值。
            ConfigFileError: 值文件读不成配置。
            ConfigReferenceError: `file=` 的引用名指向仓根之外，或被引用的文件不存在。
        """
        setting = default is not MISSING or type is not MISSING or bool(doc) or file is not None
        if setting:
            options = _Options(declare_type=type, doc=doc, file=file, force=force)
            return self._assign(path, default, options=options)
        return self._read(path)

    def _assign(self, path: str, default: object, options: _Options) -> object:
        """写侧：声明（第一次）或强写（`force=True`）。"""
        site = self._call_site()
        if path in self._declarations:
            if not options.force:
                original = self._declarations[path].site
                raise ConfigDuplicateError(
                    f"配置项 {path!r} 已经有值：代码不许重复赋值（先声明于 {original}）。"
                    "改值请改配置文件，或显式 force=True"
                )
            spec = self._declarations[path].spec
            value = check_type(self._plain(default, path), spec)
            self._pending[path] = value
            self._session[path] = value
            LOGGER.debug("强写配置项 %s = %r", path, value)
            return value

        if options.declare_type is not MISSING:
            spec = spec_of(options.declare_type)
        else:
            spec = spec_of(type(default))
        if options.file is not None:
            default = self._file_reference(path, options.file)
        # 没有默认值时（只给了 type / doc / file）不往值文件里补：那种键的值必须由文件给。
        declared: object = (
            MISSING if default is MISSING else check_type(self._plain(default, path), spec)
        )
        item = _Item(
            spec=spec,
            default=declared,
            doc=options.doc,
            site=site,
            module=site.module,
            qualname=site.qualname,
        )
        self._declarations[path] = item
        self._seen.add(path)
        if declared is not MISSING:
            plain = cast("JsonValue", declared)
            self._session[path] = plain
            self._pending[path] = plain
        self._check_current_value(path)
        return declared

    def _check_current_value(self, path: str) -> None:
        """声明之后立刻看得见的那份值（文件里的）也要过判据：坏值当场报，不等到读它的那一刻。"""
        loaded = self._load()
        if path in loaded:
            self._check_read(path, loaded[path])

    def _read(self, path: str) -> JsonValue:
        """读侧：待写 → 本会话 → 文件 → 声明的默认值（没有默认值就报错）。

        四条来源都过同一道类型判据：文件是人手改过的、写侧是代码给的，两边都不该绕过校验。
        """
        value = self._source(path)
        if value is MISSING:
            if path in self._elsewhere:
                site = self._elsewhere[path].site
                raise ConfigKeyError(f"配置项 {path!r} 的声明在 {site}，本处没声明它，读不到")
            raise ConfigKeyError(f"配置项 {path!r} 没有值可读：它不在值文件里，声明处也没有默认值")
        return self._check_read(path, cast("JsonValue", value))

    def _source(self, path: str) -> object:
        """这条键此刻的值从哪来：待写（含强写）→ 本会话 → 文件 → 声明的默认值。"""
        if path in self._pending:
            return self._pending[path]
        if path in self._session:
            return self._session[path]
        loaded = self._load()
        if path in loaded:
            return loaded[path]
        if path in self._declarations:
            return self._declarations[path].default
        return MISSING

    def _check_read(self, path: str, value: JsonValue) -> JsonValue:
        """读回来的值也过一遍类型判据：人手改坏文件同样是当场报错，不静默当别的类型用。"""
        item = self._declarations.get(path)
        if item is None:
            return value
        return check_type(value, item.spec)

    def _plain(self, value: object, path: str) -> JsonValue:
        """把默认值收进 JSON 值域：非 JSON 值在这里被拦下，而不是等落盘时崩。"""
        if isinstance(value, list | dict | str | bool | int | float) or value is None:
            return value
        raise ConfigTypeError(
            f"配置项 {path!r} 的默认值类型是 {type(value).__name__}，落不成 JSON："
            "可用的是 int / float / bool / str / list / dict / None"
        )

    # ---- 落盘：四条通路共用这一段 ---- #

    def sync(self) -> SyncResult:
        """把待写的一批落盘（值文件 + 词表），并交出这次新增 / 改动了哪些键。

        日常写法里不出现它：它只强制落盘，不划批次。工程工具与测试要"文件此刻是对的"时才调——
        例如 `--check` 类工具不先调它，就是在跟旧文件比。
        """
        added, changed = self._flush()
        return SyncResult(
            added=tuple(added),
            changed=tuple(changed),
            value_path=self.settings_path(),
            schema_path=self.schema_path(),
        )

    def plan(self) -> tuple[str, ...]:
        """只算不写：此刻若落盘，值文件里会有哪些键在内容上发生变化。

        判据是**内容**：键已在文件里且值相同就不算变化（于是规范化键序这类无谓改写不会报漂移）。
        """
        payload = self._payload()
        loaded = self._load()
        return tuple(
            sorted(
                path
                for path, value in payload.items()
                if path not in loaded or loaded[path] != value
            )
        )

    def _flush(self) -> tuple[list[str], list[str]]:
        """真正落盘的一段：值文件与词表。**四条通路都走这里**（默认退出 / sync / force）。

        **词表只增不删**：被 import 到的那个部分进程只认得一部分配置，让它按本会话的声明
        整份重写词表，等于用"我没加载到"冒充"这条配置没有了"——实测过：一份只导入 `core`
        的进程退出，就把 `storage.*` 那几条从词表里抹掉了。故写之前先与盘上那份**合并**：
        同名条目由新算的顶掉，其余原样留着。

        代价写在明处：一条声明从代码里删掉之后，它在词表里会**留成僵尸**。那份文件是人可以
        改的投影，要清就手工清——总比每次跑测试都被削一遍好。
        """
        if self._seen:
            fresh = schema.build(self._entries())
            merged = _merge_vocabulary(self.schema_path(), fresh)
            self._write_if_changed(self.schema_path(), _dump(merged))
        payload = self._payload()
        loaded = self._load()
        added = [key for key in payload if key not in loaded]
        changed = [key for key, value in payload.items() if key in loaded and loaded[key] != value]
        removed = [key for key in loaded if key not in payload]
        if added or changed or removed or not self.settings_path().is_file():
            written = {SCHEMA_KEY: self._schema_reference(), **payload}
            self._write_if_changed(self.settings_path(), _dump(written))
            loaded.clear()
            loaded.update(payload)
        self._pending.clear()
        return sorted(added), sorted(changed) + sorted(removed)

    def _payload(self) -> dict[str, JsonValue]:
        """值文件此刻该有的内容（按键名排序，`$schema` 在落盘时补在最前）。

        两段合成，次序即优先级：

        1. **用户留在文件里的键**（:meth:`_owns_value` 判为引擎没有值可写的那些）；
        2. **本会话声明且带默认值的键**——声明是事实源，文件里的旧值在这里被顶掉。

        归属按"引擎手里有没有值"判，两条各堵住一类静默丢值：

        - **只声明、没给默认值的键**（只写了 `type` / `doc` / `file`）：值只能由文件给，
          落盘时若把它算作引擎管的键，`_flush` 会当成"应删除"清掉用户写下的那一行；
        - **扫描登记的键（`_elsewhere`）**：扫描只说明"全仓有这一条声明"，本会话并未声明它，
          故值同样只能由文件给；它既不进第二段（不会凭空多出一行编出来的数据），
          也不从第一段里剔除（不会删掉用户已有的值）。
        """
        loaded = self._load()
        user = {key: value for key, value in loaded.items() if not self._owns_value(key)}
        merged = {**user, **self._session}
        return {key: merged[key] for key in sorted(merged)}

    def _owns_value(self, key: str) -> bool:
        """这条键的值归不归引擎管：**登记过且声明里带着可写的值**才算。"""
        item = self._declarations.get(key)
        return key in self._seen and item is not None and item.default is not MISSING

    def _schema_reference(self) -> str:
        """值文件顶部那句 `$schema`：指向词表，按仓根算相对路径（搬仓不失效）。"""
        try:
            return str(
                self.schema_path().resolve().relative_to(self.settings_path().parent.resolve())
            ).replace("\\", "/")
        except ValueError:
            return str(self.schema_path())

    def _entries(self) -> list[Declared]:
        """声明登记项：本会话声明过的 + 别处声明过又没在本会话声明的，按键名排序。"""
        entries: list[Declared] = []
        for path in sorted(set(self._declarations) | set(self._elsewhere)):
            item = self._declarations.get(path) or self._elsewhere[path]
            entries.append(
                Declared(
                    path=path,
                    item=item,
                    module=item.module,
                    qualname=item.qualname,
                    site=item.site,
                )
            )
        return entries

    def _write_if_changed(self, path: Path, text: str) -> None:
        """写一份产物：内容没变就不动文件（避免无谓的时间戳变更）。"""
        new = text if text.endswith("\n") else text + "\n"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file() and path.read_text(encoding="utf-8") == new:
                return
            path.write_text(new, encoding="utf-8", newline="\n")
        except OSError:
            # 只读盘 / 无权限：它是投影，写不出去不影响本次运行。
            LOGGER.warning("配置投影写不出去（只读盘？）：%s", path)

    # ---- 文件引用的解析 ---- #

    def _file_reference(self, path: str, file: str) -> str:
        """把 `file=` 落成引用名：默认同层级的 `<字段名>.<类型>`，且被引用的文件必须已在。

        引用名由声明处算出来，**不取默认值**——那条通道上默认值就是引用名本身，
        再让它参与推导等于自己指自己（`name` 参数因此没有存在的必要）。
        """
        kind = FILE_TYPES.get(file, file)
        field = path.rsplit(".", maxsplit=1)[-1]
        reference = f"{field}.{kind}" if field else f"settings.{kind}"
        target = (self.settings_path().parent / reference).resolve()
        root = self.config_root().resolve()
        if root not in target.parents:
            raise ConfigReferenceError(f"配置项 {path!r} 的文件引用 {reference!r} 指向仓根之外")
        if not target.is_file():
            raise ConfigReferenceError(
                f"配置项 {path!r} 引用的文件 {reference!r} 不存在："
                f"本体要放好（相对 {self.settings_path().parent}）"
            )
        return reference

    # ---- 读出与登记：给工具用的几面 ---- #

    def declared(self, path: str) -> Declared:
        """查一条登记项；没有声明过的键即报错（工具用它渲染，不猜）。"""
        item = self._declarations.get(path) or self._elsewhere.get(path)
        if item is None:
            raise ConfigKeyError(f"配置项 {path!r} 没有声明过")
        return Declared(
            path=path,
            item=item,
            module=item.module,
            qualname=item.qualname,
            site=item.site,
        )

    def entries(self) -> tuple[Declared, ...]:
        """全部登记项（按键名排序）：词表与工具遍历用。"""
        return tuple(self._entries())

    def used(self) -> frozenset[str]:
        """本会话声明过的键：工具用它列出"这一轮动过哪些配置"。"""
        return frozenset(self._declarations)

    def reduce(self, manifest: Mapping[str, str]) -> tuple[str, ...]:
        """按一份「键 → 模块名」的清单登记声明，**不执行任何模块**；返回实际登记的键。

        这是**扫描**那条路的入口：拿全仓 ``conf("…")`` 调用点扫出来的清单（`ast`，不执行代码）
        重建登记表。于是"配置有哪些键"既不必事先登记在一张表里（那张表本身就是漏登记的破洞），
        也不必跑起整个程序。

        这些键按"别处声明的项"登记：本会话若没人声明它，读取时会报错指出声明在哪个模块，
        而不是静默取一边。清单里的模块名只用于词表的归属一栏。
        """
        added: list[str] = []
        for path in sorted(manifest):
            if path in self._declarations:
                continue
            self._elsewhere[path] = _Item(
                spec=spec_of(type(None)),
                default=None,
                doc="",
                site=self._call_site(depth=_REDUCE_CALLER_DEPTH),
                module=manifest[path],
            )
            added.append(path)
        return tuple(added)

    # ---- 路径与装配 ---- #

    def config_root(self) -> Path:
        """配置根目录：显式给的、环境旋钮指的、或仓根下的 `config/`。"""
        if self._root is not None:
            return self._root
        from_env = os.environ.get(ROOT_ENV)
        if from_env:
            return Path(from_env)
        return Path(__file__).resolve().parents[3] / CONFIG_DIRNAME

    def settings_path(self) -> Path:
        """值文件：单文件投影（`config/settings.json`）。"""
        return self.config_root() / VALUE_FILENAME

    def loaded_keys(self) -> frozenset[str]:
        """当前值文件里已经有哪些键（读缓存，不含本会话还没落盘的声明）。

        给工程工具用：它要拿"文件里有什么"去比"声明有哪些"，而不是看内存里的待写。
        """
        return frozenset(self._load())

    def schema_document(self) -> dict[str, Any]:
        """整份词表（现算，不读文件）：给文档投影与防漂移比对用。

        **不落盘也不改盘**：它只是把声明算成一份 JSON Schema，读它的人决定怎么用——
        `scripts/docgen.py` 拿它渲染参考页，测试拿它与入库的那份逐字比对。
        """
        return schema.build(self._entries())

    def declaration_keys(self) -> frozenset[str]:
        """本会话真正声明过的键（登记表里的），**不含**扫描登记的"别处声明"。

        工具拿它做"缺 / 多"的比对：扫描登记的键只知道名字，不知道默认值与说明，
        不该被当成"值文件里必须有"。
        """
        return frozenset(self._declarations)

    def schema_path(self) -> Path:
        """词表：`config/schema/settings.json`（值文件顶部那句 `$schema` 指向它）。"""
        return self.config_root() / SCHEMA_DIRNAME / VALUE_FILENAME

    def use(self, root: Path | None) -> None:
        """把配置根换成别的目录（或换回默认），并丢掉已读的缓存（测试与嵌入式部署用）。"""
        self._root = root
        self._loaded = None

    # ---- 内部：读文件、数出处 ---- #

    def _load(self) -> dict[str, JsonValue]:
        """读值文件（一次，之后走缓存）；文件不在算空对象，读不成配置即报错。"""
        if self._loaded is None:
            self._loaded = self._read_file()
        return self._loaded

    def _read_file(self) -> dict[str, JsonValue]:
        """把值文件读成 `键 → 值`；坏文件当场报错，不猜也不自动修。"""
        path = self.settings_path()
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigFileError(f"值文件读不出来：{path}（{error}）") from error
        if not isinstance(data, dict):
            raise ConfigFileError(f"值文件的根不是对象：{path}")
        return {
            str(key): cast("JsonValue", value) for key, value in data.items() if key != SCHEMA_KEY
        }

    def _call_site(self, *, depth: int = _CALLER_DEPTH) -> CallSite:
        """调用点的出处：从本帧往上找第 `depth` 层的代码位置。"""
        frame = inspect.currentframe()
        for _ in range(depth):
            if frame is None:
                break
            frame = frame.f_back
        if frame is None:
            return CallSite(module="?", file="?", line=0)
        filename = frame.f_code.co_filename
        try:
            shown = Path(filename).resolve().relative_to(Path.cwd()).as_posix()
        except ValueError:
            shown = Path(filename).as_posix()
        return CallSite(
            module=str(frame.f_globals.get("__name__", "?")),
            file=shown,
            line=frame.f_lineno,
            qualname="" if frame.f_code.co_name == "<module>" else frame.f_code.co_name,
        )


def _dump(payload: dict[str, Any]) -> str:
    """把一份产物渲染成 JSON 文本（中文不转义、两格缩进、末尾留一个换行）。"""
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _merge_vocabulary(path: Path, fresh: dict[str, Any]) -> dict[str, Any]:
    """把本会话算出的词表并进盘上那份：**`properties` 一层只增不删**，其余头部照新算的。

    那份文件是"全部声明的并集"，不是"最后一次退出的那个进程手里有的那些"。同名条目由新算
    的顶掉，其余旧条目原样留着。读不出来（不在 / 坏 JSON / 形状不对）就按新的写——
    一份坏文件不该挡住落盘。
    """
    if not path.is_file():
        return fresh
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fresh
    if not isinstance(found, dict):
        return fresh
    old = found.get("properties")
    new = fresh.get("properties")
    if not isinstance(old, dict) or not isinstance(new, dict):
        return fresh
    return {**fresh, "properties": {**old, **new}}


def _atexit_sync() -> None:
    """退出时把待写的一批落盘：这是"默认只记一笔"的保底通路。

    **退出路径不允许抛**：它是投影，失败只记日志（`_write_if_changed` 已经吞掉 OSError）。
    """
    with contextlib.suppress(Exception):
        conf.sync()


#: 进程级配置面：`from core.conf import conf` 之后任何地方都能用
conf = Config()
conf.__doc__ = (
    "配置面：声明与取值同形。`conf(key, default, ...)` 声明、`conf(key)` 取值；"
    "写只记一笔、退出时统一落盘，`sync()` 立刻刷、`force=True` 强写。"
)
atexit.register(_atexit_sync)

__all__ = [
    "CONFIG_DIRNAME",
    "ROOT_ENV",
    "SCHEMA_DIRNAME",
    "VALUE_FILENAME",
    "CallSite",
    "Config",
    "Declared",
    "SyncResult",
    "conf",
]
