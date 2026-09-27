# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""配置引擎：**声明即事实，两个投影落在磁盘上**。

作者 2026-09-26 定的形状：

- 两套目录一一对应，同一组 key 的**两个面**::

      config/<hub>/<包树>/<file_name>.<config_file_type>   ← 值（软配置）
      schema/<hub>/<包树>/<file_name>.json                 ← 词表（永远 json）

  包树与 ``src/<包树>`` 同构（``src/core/storage/conf.py``
  → ``config/settings/core/storage/conf.json``），所以**哪个文件声明、就落哪份同名配置**。
  ``<hub>`` 是命名空间：默认 ``settings``；换一个 hub 就换一组投影（生成物 / 手写口各归各的），
  于是"生成物把别人的文件覆盖掉"这件事由**重名检查**兜住（见 :meth:`ConfEngine.conflicts`）。

- **声明是唯一事实来源**：``Cfg`` 写在声明模块的类体里，绑上即报到（`core.types.cfg` 登记表），
  引擎把它展开成上面两个文件。**各模块管自己的配置**——声明写在自己包里，配置端只负责展开。
- 带值注册（``Cfg("k", 4096)``）→ 两侧都出现，``config/`` 那份带值；
  不带值（``Cfg("k")``）→ 只有 ``schema/`` 出现，``config/`` 里不呈现。
- **文件引用**（``Cfg("k", file_type="yaml")``）：内容不塞进值文件，值文件里只留一行
  **引用名**——相对值文件自己所在目录解析，默认就是同层级的 ``<字段名>.<类型>``。
  于是写起来像 ``import``，整棵配置树搬到哪里都成立；引擎读它时按扩展名选解析器。

取值三条（作者原话的落地）：

===============  ==========================  ====================================
文件里的状态      默认值                      行为
===============  ==========================  ====================================
key 在、值空      任意                        **报错**（``ConfigValueError``）——不猜
key 丢了          有（带值注册）              **补回默认值**（文件删了也能重展开）
key 丢了          没有                        **报错**（``ConfigKeyError``）——补不了
===============  ==========================  ====================================

**用户改过的值不会被覆写**：补只补"缺失的键"；已有的键一个字都不动。

本模块只依赖标准库与 ``core.types``；引擎**不引任何领域的配置声明**。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.types.cfg import CfgItem, items

from .errors import (
    ConfigConflictError,
    ConfigFileError,
    ConfigKeyError,
    ConfigValueError,
)

# ---- 全局默认 ----
CONFIG_PATH = "config"
"""仓根下的配置根目录名。"""

CONFIG_HUB = "settings"
"""默认 hub（命名空间）：生成物落 ``config/<hub>/…`` / ``schema/<hub>/…``。

换 hub = 换一组投影；手写口（将来的个人覆写）用别的 hub，与本 hub 的生成物互不打扰。
"""

CONFIG_FILE_TYPE = "json"
"""载体形式：json / 将来 yaml、py（换形式只换载体，语义不变）。"""

SCHEMA_FILE_TYPE = "json"
"""词表固定 json（要喂给 IDE）。"""

SETTINGS_SCHEMA_ID = "https://github.com/HanYang06/cairn/schema/settings.json"

_MODULE_ROOTS: dict[str, str] = {
    "app": "src/app",
    "core": "src/core",
    "feature": "src/feature",
    "ui_tools": "src/ui_tools",
}

_REPO_MARKERS = ("pyproject.toml", ".git")


def find_root(start: Path | None = None) -> Path:
    """仓根：``CAIRN_ROOT`` 优先，否则从 ``start`` 向上找 ``pyproject.toml`` / ``.git``。"""
    override = os.environ.get("CAIRN_ROOT")
    if override:
        candidate = Path(override)
        if candidate.is_dir():
            return candidate
    here = (start or Path(__file__)).resolve()
    for parent in (here, *here.parents):
        if any((parent / marker).exists() for marker in _REPO_MARKERS):
            return parent
    return here.parent


def _module_root(module: str) -> Path:
    """模块的顶层包在仓内的根（``core.storage.conf`` → ``src/core``）。"""
    head = module.partition(".")[0]
    return Path(_MODULE_ROOTS.get(head, f"src/{head}"))


def source_path(module: str) -> Path:
    """模块名 → 仓内源码文件路径（``core.storage.conf`` → ``src/core/storage/conf``）。

    未知顶层包退化为 ``src/<顶层>``，不报错：声明出现在哪都该能落地。
    """
    _, _, rest = module.partition(".")
    return _module_root(module).joinpath(*[part for part in rest.split(".") if part])


@dataclass(frozen=True, slots=True)
class Folder:
    """一份配置投影：源码文件 + 它在包树里的位置 + hub。

    ``src/core/storage/conf.py`` ↔ ``config/settings/core/storage/conf.json``
    ↔ ``schema/settings/core/storage/conf.json``。
    """

    tree: Path
    """包树里的相对路径（``core/storage/conf``）。"""

    source: Path
    """它在仓库里的源码路径（``src/core/storage/conf``，给人看）。"""

    name: str
    """源文件名（不含 ``.py``；``conf``）。"""

    hub: str = CONFIG_HUB
    """命名空间（``settings``）：生成物 / 手写口各用一个，互不覆盖。"""

    @classmethod
    def of(cls, module: str, *, hub: str = CONFIG_HUB, source: Path | None = None) -> Folder:
        """由模块名建投影坐标（``core.storage.conf`` → ``core/storage/conf``）。"""
        found = source if source is not None else source_path(module)
        root = _module_root(module)
        return cls(tree=found.relative_to(root.parent), source=found, name=found.name, hub=hub)

    @classmethod
    def of_path(cls, relative: Path, *, hub: str = CONFIG_HUB) -> Folder:
        """由配置树里的相对路径反推（``core/storage/conf.json`` 解析用）。

        ``source`` 必须与 :meth:`of` 算出**同一个值**：``Folder`` 是 frozen dataclass，
        ``source`` 参与相等性与哈希——差一层目录（如 ``src/core/core/storage/conf``）
        就会让「按路径找回声明」静默失配，重名检查随之退化。故以模块根的**父目录**
        （``src``）为基准拼 ``tree``。
        """
        tree = relative.with_suffix("")
        parts = tree.parts
        root = Path(_MODULE_ROOTS.get(parts[0], f"src/{parts[0]}")) if parts else Path("src")
        return cls(tree=tree, source=root.parent / tree, name=tree.name, hub=hub)


class ConfEngine:
    """配置引擎：登记表 → 文件投影，文件 → 值。

    ``root`` / ``base`` 可覆盖（打包后仓根不在时用得上；测试用临时目录隔离）。
    """

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        hub: str = CONFIG_HUB,
        base: str = CONFIG_PATH,
        file_type: str = CONFIG_FILE_TYPE,
    ) -> None:
        self.root = Path(root) if root is not None else find_root()
        self.hub = hub
        self.base = base
        self.file_type = file_type
        self._cache: dict[str, Any] = {}

    # ---- 路径 ----
    def config_path(self, folder: Folder) -> Path:
        """值文件：``config/<hub>/<包树>/<name>.<type>``。"""
        name = f"{folder.name}.{self.file_type}"
        return self.root / self.base / folder.hub / folder.tree.parent / name

    def schema_path(self, folder: Folder) -> Path:
        """词表文件：``schema/<hub>/<包树>/<name>.<SCHEMA_FILE_TYPE>``。"""
        base = self.root / "schema" / folder.hub / folder.tree.parent
        return base / f"{folder.name}.{SCHEMA_FILE_TYPE}"

    def reference_path(self, item: CfgItem, value: str) -> Path:
        """被引用文件的实际路径：引用名**相对值文件所在目录**解析。

        默认引用名就是同层级的 ``<字段名>.<类型>``（``tables.yaml``），
        故写起来像 ``import``，搬整棵配置树也不会失效。
        **只收相对引用**：绝对路径绑死本机目录，配置文件是要跟仓走的。
        """
        text = value.replace("\\", "/").strip()
        if not text:
            raise ConfigValueError(f"被引用配置文件的引用名是空的：{item.key}")
        candidate = Path(text)
        if candidate.is_absolute() or candidate.drive:
            raise ConfigValueError(
                f"被引用配置文件必须写相对引用（绝对路径搬不动仓）：{item.key} = {value!r}"
            )
        return self.config_path(self._folder_of(item)).parent / candidate

    def _referenced(self, item: CfgItem, value: str) -> Any:
        """读被引用文件（**值就是这个文件的内容**）；缺失或读不出即报错，不猜。

        扩展名决定解析器：``yaml`` 走安全加载，其余按 JSON。
        """
        path = self.reference_path(item, value)
        if not path.is_file():
            raise ConfigValueError(f"被引用的配置文件不存在：{path}（{item.key}）")
        text = path.read_text(encoding="utf-8")
        if item.file_type == "yaml":
            import yaml  # noqa: PLC0415 — 只在这条路径上需要

            try:
                return yaml.safe_load(text)
            except yaml.YAMLError as exc:
                raise ConfigValueError(f"被引用的配置文件解析失败：{path}（{exc}）") from exc
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigValueError(f"被引用的配置文件解析失败：{path}（{exc}）") from exc

    def index_path(self) -> Path:
        """总词表（给人看的入口，含 ``$id``）。"""
        return self.root / "schema" / f"{self.hub}.json"

    def _folder_of(self, item: CfgItem) -> Folder:
        return Folder.of(item.module, hub=self.hub)

    def _declared(self) -> dict[Folder, list[CfgItem]]:
        """按源文件归拢全部声明。"""
        grouped: dict[Folder, list[CfgItem]] = {}
        for item in items():
            grouped.setdefault(self._folder_of(item), []).append(item)
        for found in grouped.values():
            found.sort(key=lambda one: one.key)
        return grouped

    def _ordered(self, folder: Folder, merged: dict[str, Any]) -> dict[str, Any]:
        """值文件的键序：**在册键按声明顺序在前，用户自己加的键在后**。

        只调顺序、不删不改值；:meth:`plan` 与 :meth:`_write_value_file` **共用这一处**——
        `_stale()` 按文本逐字节比较，两处若各排一种序，写出来的文件会被 `--check` 误报成漂移。
        """
        declared = self._declared().get(folder, ())
        ordered = {item.key: merged[item.key] for item in declared if item.key in merged}
        ordered.update({key: value for key, value in merged.items() if key not in ordered})
        return ordered

    # ---- 投影：plan（只看不写）/ sync（写）----
    def plan(self) -> list[tuple[Path, dict[str, Any], bool]]:
        """算出两个投影**应该**是什么样，返回 ``[(文件, 内容, 是否与磁盘不一致)]``。

        只看不写——``--check`` 用它判漂移，``sync`` 用它落盘（同一份事实，一处推算）。
        """
        from .schema import folder_schema  # noqa: PLC0415 — 避免加载期互引

        plans: list[tuple[Path, dict[str, Any], bool]] = []
        for folder, declared in self._declared().items():
            value_file = self.config_path(folder)
            current = self._read_file(value_file)
            merged = {**current}
            for item in declared:
                if item.key in merged:
                    continue  # 值由人定：已有的值一个字都不动（含文件引用的引用名）
                if item.file_type:
                    # 文件引用：值文件里只留一行"这项在哪个文件"，本体在被引用文件里。
                    merged[item.key] = item.reference
                elif item.fillable:
                    merged[item.key] = item.default
            payload = {
                "$schema": self._relative_schema(value_file),
                **self._ordered(folder, merged),
            }
            plans.append((value_file, payload, self._stale(value_file, payload)))
            schema_file = self.schema_path(folder)
            schema_body = folder_schema(declared)
            plans.append((schema_file, schema_body, self._stale(schema_file, schema_body)))
        # 总词表只有一份：放在循环外入队一次（放在循环里会按 folder 数重复追加，且重复计算）。
        index = self.index_path()
        index_body = self._root_schema()
        plans.append((index, index_body, self._stale(index, index_body)))
        return plans

    def conflicts(self, plans: list[tuple[Path, dict[str, Any], bool]] | None = None) -> list[str]:
        """**重名检查**：目标路径上是否压着一份"不是本引擎写的"文件。

        判据（只在目标已存在、且内容与"本引擎要写的"不一致时才看）：

        1. 文件读不成投影（不是 JSON / 根不是对象）→ 冲突（`config` 侧同时抛
           :class:`ConfigFileError`，那是"文件坏了"，比"重名"更准）；
        2. 有 ``$schema`` 但指向别处 → 冲突（别人的文件）；
        3. 没有 ``$schema``，也找不到本引擎为它登记过的键 → 冲突。

        命中即**拒写**（:meth:`sync` 抛 :class:`ConfigConflictError`），
        由调用方决定搬迁还是换 hub——**绝不覆盖别人的文件**。

        坏文件是**先收集、末尾统一抛**：中途抛出会丢掉已经查到的冲突项，
        调用方一次只能看到一个毛病，反而更难排查。
        """
        found: list[str] = []
        broken: list[Path] = []
        for path, payload, stale in plans if plans is not None else self.plan():
            if not stale or not path.exists():
                continue
            try:
                clash = self._clash(path, payload)
            except ConfigFileError:
                broken.append(path)
                continue
            if clash:
                found.append(clash)
        if broken:
            detail = "；".join(str(path) for path in broken)
            others = f"（另有 {len(found)} 处重名：{'；'.join(found)}）" if found else ""
            raise ConfigFileError(f"配置文件不可读：{detail}{others}")
        return found

    # 守卫式逐条排除：每条判据一个提前返回，比层层嵌套好读（故放行 PLR0911）。
    def _clash(self, path: Path, payload: dict[str, Any]) -> str | None:  # noqa: PLR0911
        """该目标路径上是否压着"不是本引擎写的"文件；是则返回一句说明，否则 ``None``。

        判据只此一处：:meth:`conflicts` 与 :meth:`set` 共用，
        免得"批量写守规矩、单值写不守"。
        """
        if not path.exists():
            return None
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            if (self.root / self.base) in path.parents:
                raise ConfigFileError(f"配置文件不可读：{path}") from exc
            return f"{path}（不是合法 JSON，不敢覆盖）"
        if not isinstance(existing, dict):
            return f"{path}（根不是对象，不敢覆盖）"
        if not existing:
            # 空对象（`{}`）：没有任何"别人的内容"可覆盖，补键不构成侵占。
            return None
        marker = str(existing.get("$schema", ""))
        if marker:
            if marker != str(payload.get("$schema", "")):
                return f"{path}（$schema 指向别处：{marker}）"
            return None
        if not any(key in existing for key in self._keys_of(path)):
            return f"{path}（无 $schema，也不像本引擎的投影）"
        return None

    def _keys_of(self, path: Path) -> tuple[str, ...]:
        """这个投影路径"像自己人"的证据：本引擎为它**登记过**的具体键。

        找不回声明（路径不在声明树里）就返回空——空证据即「不像自己人」，
        重名检查按**拒写**处理（fail closed：宁可拦下来交人工，也不覆盖别人的文件）。
        """
        try:
            folder = self._folder_of_path(path)
        except (ValueError, IndexError):
            return ()
        return tuple(item.key for item in self._declared().get(folder, ()))

    def sync(self) -> list[tuple[Path, bool]]:
        """把声明展开成 ``config`` / ``schema`` 两侧的文件。

        - ``config`` 侧：只补**缺失的键**（用户已有的值一个字不动）；
        - ``schema`` 侧：整份重写（它是投影，不是数据）。

        **先过重名检查**：命中冲突就不写、抛 ``ConfigConflictError``（不覆盖别人的文件）。

        返回 ``[(文件, 这次是否真写了)]``。
        """
        plans = self.plan()
        clashes = self.conflicts(plans)
        if clashes:
            raise ConfigConflictError("配置投影与已有文件重名，拒写：" + "；".join(clashes))
        written: list[tuple[Path, bool]] = []
        for path, payload, stale in plans:
            if stale:
                self._write_json(path, payload)
            written.append((path, stale))
        self._cache.clear()
        return written

    def describe(self) -> list[dict[str, Any]]:
        """当前登记的声明（字典形式，给工具与调试用）。"""
        return [
            {
                "key": item.key,
                "type": _type_label(item.type),
                "default": item.default,
                "doc": item.doc,
                "fillable": item.fillable,
                "empty_ok": item.empty_ok,
                "module": item.module,
                "owner": item.owner,
            }
            for item in items()
        ]

    # ---- 取值 ----
    def get(self, key: str, default: Any = None) -> Any:
        """取一个配置值：文件里有 → 文件说了算；没有 → 缺省 / 报错。

        三条规则见模块 docstring；**key 在但值为空**永远报错（空就是被改坏了）。
        """
        if key in self._cache:
            return self._cache[key]
        declared = _declared_map().get(key)
        folder = self._folder_of(declared) if declared is not None else None
        value = None
        found = False
        if folder is not None:
            data = self._read_file(self.config_path(folder))
            found = key in data
            value = data.get(key)
        if found and _is_empty(value):
            if declared is not None and declared.empty_ok:
                return self._remember(key, declared.default)
            raise ConfigValueError(f"配置项值为空（不猜、不自动修）：{key}")
        if found:
            return self._remember(key, self._resolved_value(declared, value))
        if declared is None:
            if default is not None:
                # **不写缓存**：缓存键只有 key，把调用方给的 default 记进去，
                # 下次换一个 default 取同一个 key 会拿到旧值。
                return default
            raise ConfigKeyError(f"配置项未登记，文件里也没有：{key}")
        if declared.fillable:
            self._repair(declared)
            return self._remember(key, declared.default)
        raise ConfigKeyError(f"配置项丢了且没有默认值可以补：{key}")

    def _resolved_value(self, declared: CfgItem | None, value: Any) -> Any:
        """文件引用的项要再走一步：文件里那一行只是**引用名**，本体在别处。

        其余项照原值交回——取值面因此只有这一处分叉，调用方也不必知道文件引用这回事。
        """
        if declared is None or not declared.file_type:
            return value
        if not isinstance(value, str):
            raise ConfigValueError(
                f"文件引用的项要写引用名（字符串），得到 {type(value).__name__}：{declared.key}"
            )
        return self._referenced(declared, value)

    def set(self, key: str, value: Any) -> None:
        """写一个值进配置文件（**这是配置唯一的写入口**）。

        写入前过一遍 :meth:`_clash`：路径上压着别人的文件时同样**拒写**——
        「绝不覆盖别人的文件」不是只有批量写才守；单值写也同样整份重写目标文件。
        """
        declared = _declared_map().get(key)
        if declared is None:
            raise ConfigKeyError(f"配置项未登记，不能写：{key}")
        path = self.config_path(self._folder_of(declared))
        self._write_value_file(path, {**self._read_file(path), key: value})
        self._cache.pop(key, None)

    def reload(self) -> None:
        """丢掉缓存（外部直接改了文件后调）。"""
        self._cache.clear()

    # ---- 内部 ----
    def _repair(self, item: CfgItem) -> None:
        """补一条缺失的默认值（只补缺失的键，不碰别的）。"""
        path = self.config_path(self._folder_of(item))
        data = self._read_file(path)
        if item.key not in data:
            data[item.key] = item.default
            self._write_value_file(path, data)

    def _remember(self, key: str, value: Any) -> Any:
        self._cache[key] = value
        return value

    def _read_file(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigFileError(f"配置文件不可读：{path}") from exc
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise ConfigFileError(f"配置文件根必须是对象：{path}")
        raw.pop("$schema", None)
        return raw

    def _write_value_file(self, path: Path, data: dict[str, Any]) -> None:
        """写值文件：**键序规范化 + 顶部带指向词表的 ``$schema`` + 重名检查**。

        所有值文件的写入口都走这里（:meth:`set` 与 :meth:`_repair`），
        故「绝不覆盖别人的文件」与「键序与 :meth:`plan` 一致」只需守一道。
        """
        payload = {
            "$schema": self._relative_schema(path),
            **self._ordered(self._folder_of_path(path), data),
        }
        clash = self._clash(path, payload)
        if clash:
            raise ConfigConflictError(f"配置投影与已有文件重名，拒写：{clash}")
        self._write_json(path, payload)

    def _relative_schema(self, path: Path) -> str:
        """值文件顶部的 ``$schema``：相对指向它对应的词表文件。"""
        schema_file = self.schema_path(self._folder_of_path(path))
        return Path(os.path.relpath(schema_file, path.parent)).as_posix()

    def _folder_of_path(self, path: Path) -> Folder:
        """由值文件路径反推投影（``config/<hub>/<包树>/<name>.<type>``）。"""
        relative = path.relative_to(self.root / self.base)
        return Folder.of_path(Path(*relative.parts[1:]), hub=relative.parts[0])

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        """写一份投影：行尾固定为 LF，且**先写同目录临时文件再改名**（原子替换）。

        整份覆盖若在中途被 kill，磁盘上会留下截断的非法 JSON；下一轮 `plan()` 读到它即抛
        `ConfigFileError`，而引擎的口径是「不自动修」——那个坏文件就此把库锁死，只能人工处理。
        临时文件 + `os.replace` 让中断时旧文件仍然完整。
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp")
        tmp.write_text(_dumps(payload), encoding="utf-8", newline="\n")
        tmp.replace(path)

    def _stale(self, path: Path, payload: dict[str, Any]) -> bool:
        """磁盘上这份投影是否已经与生出来的一致（一致则不改动）。"""
        if not path.exists():
            return True
        try:
            return path.read_text(encoding="utf-8") != _dumps(payload)
        except OSError:
            return True

    def _root_schema(self) -> dict[str, Any]:
        from .schema import root_schema  # noqa: PLC0415

        return root_schema(self._declared())


def _dumps(payload: dict[str, Any]) -> str:
    """投影文件的统一写法：两空格缩进、中文原样、结尾一个换行。"""
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _declared_map() -> dict[str, CfgItem]:
    """登记表按路径索引（``Cfg`` 登记的口）。"""
    return {item.key: item for item in items()}


def _type_label(hint: Any) -> str:
    """类型提示的可读名：普通类取 ``__name__``，联合 / 泛型走 ``str()``。"""
    if hint is None:
        return ""
    return hint.__name__ if isinstance(hint, type) else str(hint)


def _is_empty(value: Any) -> bool:
    """空值的口径：``None`` / 空串 / 空容器（``0`` 与 ``False`` **不算空**）。"""
    if value is None or value == "":
        return True
    return isinstance(value, (list, dict, tuple, set)) and not value


conf = ConfEngine()
"""默认引擎单例（仓根自动探测；要用别的根就自己 ``ConfEngine(root)``）。

名字就叫 ``conf``：包名 ``core.conf`` 与这个**对象**同名没问题，
真正会打架的是包内同名**子模块**（所以内核自己的声明模块叫 `params.py`，不叫 `conf.py`）。
"""


__all__ = [
    "CONFIG_FILE_TYPE",
    "CONFIG_HUB",
    "CONFIG_PATH",
    "SCHEMA_FILE_TYPE",
    "SETTINGS_SCHEMA_ID",
    "ConfEngine",
    "Folder",
    "conf",
    "find_root",
    "source_path",
]
