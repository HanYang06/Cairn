# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""`Core`：**内核本体**（单例：两张对象表 + 引擎挂载点 + 最小 API）。

作者口述的设计（2026-09-22）：

- **内核是单例**（工程约束）：多个内核实例"本身可能就是个灾难"，于是**就约束它只有一个**；
  不做守护实例——它崩了等于进程崩了。
- 两张**对象表属于内核**（不是引擎）：
  - **表一 · 内核内部对象**：配置、信号、存储……固定件，**硬编码**，与内核同生共死；
  - **表二 · 内核外部对象**：笔记、项目这类**非固定**对象，随生命周期诞生 / 消失。
- **引擎受内核管辖**：内核挂着引擎；挂它时**顺手把两张表传给引擎**。引擎自己**不持表**。
- **自动注册靠继承**：领域对象继承内核（或继承一个"领域专用对象"再继承内核），
  父类在 ``__init_subclass__`` 里替子类登记——绝大多数对象**不用自己管注册**。
- **孤儿类型**：不进表 = 存在但不可达 = 等于不存在。注册是"成立"的条件。
- **API 要短**：要获取 / 存 / 改什么，最终都隔离成**事件包**发给引擎；但使用方**不该为此
  写几十行**——`put` / `get` / `call` 这些方法**内部替你组包**，目标"5 行以内办完一件事"。
"""

from __future__ import annotations

from typing import Any, ClassVar

from core.signal import Outcome, Signal
from core.storage import Block
from core.types import CairnError, ObjectInfo, VerifyReport
from core.types.event import Action, Event, Intent
from core.types.kind import ROLE_DOMAIN, TypeInfo, identity_key, register, type_name, unit_names

_IDENTITIES = ("role_id", "role_name", "role_obj")

_STORAGE_ROLE = "storage"


class Core:
    """内核本体（单例）：持有两张对象表，把表交给引擎，并给出最短的调用面。"""

    _instance: ClassVar[Core | None] = None
    # 受管辖的**类型**（继承即登记；类级，因为 `__init_subclass__` 发生在类定义期）
    _types: ClassVar[dict[str, object]] = {}

    # ---- 单例（工程约束：多个内核实例是灾难，所以只允许一个）----
    def __new__(cls, *_args: Any, **_kwargs: Any) -> Core:  # noqa: PYI034 — 单例返回已有实例
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        # 只初始化一次（单例重复构造不重置状态）
        if getattr(self, "_ready", False):
            return
        # 表一 · 内核内部对象（固定件，硬编码挂载）
        internal: dict[str, dict[Any, object]] = {key: {} for key in _IDENTITIES}
        # 表二 · 内核外部对象（动态，注册进来）
        external: dict[str, dict[Any, object]] = {key: {} for key in _IDENTITIES}
        signal: Signal = Signal()  # 挂载信号引擎
        signal.connect(internal, external)
        # 全部建好之后才置就绪：中途失败时 `_ready` 仍为假，下次 `Core()` 重新初始化；
        # 先置位会让半初始化实例（无表 / 无引擎）被后续构造直接复用。
        self._internal = internal
        self._external = external
        self.signal = signal
        self._ready = True

    @classmethod
    def type_of(cls, name: str) -> object | None:
        """按名字取**受管辖的类型**（继承 `Managed` 即登记）。"""
        return cls._types.get(name)

    def role(self, name: str) -> object | None:
        """按名字取**受管辖的服务实例**（登记时建的那个）；未登记返回 ``None``。

        只返回**实例**：类型收成（:meth:`type_of`）里存的是类，混进同一条返回路径
        会让调用方拿到类却按实例使用。要类请走 :meth:`type_of`。
        """
        for table in (self._external, self._internal):
            if (found := table["role_name"].get(name)) is not None:
                return found
        return None

    @classmethod
    def register_type(cls, target: Any) -> None:
        """把一个**受管辖的类**登记进最小类型表（类型层内省用）。

        域的 ``name`` 是短名（``note``）、``type`` 是落盘类型，``data`` / ``light``
        给出依赖与最小数据单元——与旧 `Domain` 的口径一致。
        """
        declared = getattr(target, "type", "")
        kind = type_name(declared) if declared else target.__name__.lower()
        register(
            TypeInfo(
                type=kind,
                role=ROLE_DOMAIN,
                cls=target,
                name=str(getattr(target, "name", "") or target.__name__.lower()),
                deps=unit_names(getattr(target, "data", ())),
                units=unit_names(getattr(target, "light", None)) or (kind,),
            )
        )

    # ---- 表：挂 / 注册 / 查 ----
    def mount(self, name: str, obj: object) -> object:
        """把**内核固定件**挂进表一（存储 / 引擎 / 配置……）；同名旧挂件被换下。

        换下时把旧对象从三种身份格里一并摘净：只覆盖 ``role_name`` 会留下
        查得到的陈旧引用（``lookup("role_obj", 旧存储)`` 仍然命中）。

        **换下即释放**：旧挂件若有 ``close`` 就调一次——被覆盖的存储如果没人关，
        它的 sqlite 连接与载体文件句柄不会有第二次释放机会（要等到垃圾回收才报资源警告）。
        """
        previous = self._internal["role_name"].get(name)
        if previous is not None and previous is not obj:
            _forget(self._internal, previous)
            close = getattr(previous, "close", None)
            if callable(close):
                close()
        self._internal["role_name"][name] = obj
        self._internal["role_id"][str(getattr(obj, "id", "") or name)] = obj
        self._internal["role_obj"][identity_key("role_obj", obj)] = obj
        return obj

    def register(self, obj: object, *, oid: str = "", name: str = "") -> object:
        """把一个**实例**登记进表二；不进表就是孤儿。"""
        _store(self._external, obj, oid=oid, name=name)
        return obj

    def unregister(self, obj: object) -> None:
        """把一个对象从表二摘掉（**显式注销**）。"""
        _forget(self._external, obj)

    def lookup(self, identity: str, value: Any) -> object | None:
        """按身份查对象：**先表二（外部）、再表一（内部）**；找不到返回 ``None``。

        ``role_obj`` 与登记时同一套键（带类型标签），否则"拿对象查"会查不到。
        """
        if not identity:
            return None
        key = identity_key(identity, value)
        found = self._external.get(identity, {}).get(key)
        if found is not None:
            return found
        return self._internal.get(identity, {}).get(key)

    # ---- 引擎 ----
    def use(self, engine: Signal) -> Signal:
        """换一条引擎（默认自建的那条；换的时候同样把两张表交给它）。"""
        self.signal = engine
        engine.connect(self._internal, self._external)
        return engine

    # ---- 最小 API（内部代为组包；目标 5 行以内办完一件事）----
    def put(self, obj: object) -> object:
        """**存**：组一个事件包交给引擎（角色 = 存储）。

        落盘失败**显式抛出**：``store`` 抛的异常只被引擎记进 `Step.error`，
        在这里吞掉会让调用方把"没写进去"读成"存好了"（静默数据丢失）。
        """
        _raise_if_failed(self.send(Intent.PUT, self._act("store", obj=obj)), "存对象")
        return obj

    def get[T](self, cls: type[T], oid: str) -> T:
        """**取**：经存储按类型还原（``cls`` 用来还原真实类型）。"""
        return self.storage.get(cls, str(oid))  # type: ignore[no-any-return]

    def drop(self, oid: str) -> None:
        """**删**；失败显式抛出（口径同 :meth:`put`）。"""
        _raise_if_failed(self.send(Intent.DEL, self._act("drop", oid=oid)), "删对象")

    def call(self, target: object, method: str, **args: Any) -> Any:
        """**改**：对某个对象上的某个方法发一个动作（同样一行）。

        失败显式抛出：方法正常返回 ``None`` 与"动作根本没执行"不得混为一谈。
        """
        outcome = self.send(
            Intent.PUT,
            Action(role_obj=target, call_function=method, call_args=args),
        )
        _raise_if_failed(outcome, f"调用 {type(target).__name__}.{method}")
        return outcome.steps[0].result if outcome.steps else None

    def send(self, intent: Intent, *actions: Action, target: object | str = "") -> Outcome:
        """**发事件**：把动作链交给引擎；返回引擎的处理全貌（`Outcome`）。

        不带动作 = **广播**（谁关心谁听）：此时用 ``target`` 带上主体标识
        （例如"哪条笔记变了"），订阅方从事件里取。引擎是内核自带的，**永远在场**。
        """
        return self.signal.handle(Event(intent=intent, actions=list(actions), target=target))

    def storage_ids(self) -> list[str]:
        """列出库里全部对象 id（给领域列出自己那类对象用）。"""
        return list(self.storage.ids())

    @property
    def storage(self) -> Any:
        """表一里的**存储**（挂件）：进 / 出 / 找都经它。"""
        storage = self._internal["role_name"].get(_STORAGE_ROLE)
        if storage is None:
            raise CairnError("内核未挂存储：请先 core.mount('storage', Storage...)")
        return storage

    def info(self, oid: str) -> Any:
        """取对象的中立视图（类型 / 标题 / 标签 / 时间）。"""
        return self.storage.info_of(str(oid))

    def read(self, oid: str) -> bytes:
        """取对象的**主体字节**。"""
        body: bytes = self.storage.get(Block, str(oid)).read()
        return body

    def verify(self, *, deep: bool = False) -> VerifyReport:
        """巡检：逐个取回对象，收集问题（``deep`` 尚未实现，如实报错）。"""
        if deep:
            raise NotImplementedError("深度校验尚未实现")
        problems: list[str] = []
        ids = self.storage_ids()
        for block_id in ids:
            try:
                self.storage.get(Block, block_id)
            except Exception as exc:  # noqa: BLE001 — 巡检要收集所有问题，不能中断
                problems.append(f"{block_id}: {exc}")
        return VerifyReport(objects=len(ids), problems=tuple(problems))

    def gc(self, *, retention_ms: int | None = None) -> int:
        """回收未引用内容；**尚未实现**（勿静默返回 0 误导调用方）。"""
        del retention_ms
        raise NotImplementedError("pack 压实 / gc 尚未实现")

    def query(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> list[Any]:
        """只读查询（经存储；上层不 import sqlite）。"""
        rows: list[Any] = list(self.storage.query(sql, params))
        return rows

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> int:
        """写语句（经存储）。"""
        changed: int = int(self.storage.execute(sql, params))
        return changed

    def iter(self, *, type: Any = None, tags: Any = None) -> list[ObjectInfo]:
        """列出对象视图；``type`` / ``tags`` 给出时按其过滤。

        整表**一次取回**（``storage.infos()``）：逐对象查一遍会让 N 个对象触发
        N+1 次查询，并逐个把内容读进内存。
        """
        wanted = type_name(type) if type is not None else None
        wanted_tags = self._wanted_tags(tags)
        found: list[ObjectInfo] = []
        for view in self.storage.infos():
            if wanted is not None and view.type != wanted:
                continue
            if wanted_tags and not all(
                key in view.tags and (value is None or view.tags.get(key) == value)
                for key, value in wanted_tags.items()
            ):
                continue
            found.append(view)
        return found

    @staticmethod
    def _wanted_tags(tags: Any) -> dict[str, Any]:
        """把"想要的标签"归一成映射（``None`` = 只看键存在）。"""
        if tags is None:
            return {}
        if isinstance(tags, str):
            return {tags: None} if tags else {}
        if isinstance(tags, dict):
            return {str(key): value for key, value in tags.items()}
        return {str(tag): None for tag in tags}

    def close(self) -> None:
        """关库（内核本身不销毁：它是单例，存储是挂件）。"""
        storage = self._internal["role_name"].get(_STORAGE_ROLE)
        close = getattr(storage, "close", None)
        if callable(close):
            close()

    def open(self, path: Any) -> Core:
        """开（或建）一个库并挂到内核上；返回内核自身（便于链式/重开）。

        重开之前先关掉旧存储：内核是单例，旧存储若只是被覆盖，其 sqlite 连接
        与载体文件句柄不会有第二次释放机会。
        """
        from core.storage import Storage  # noqa: PLC0415 — 避免加载期互引

        self.close()
        self.mount(_STORAGE_ROLE, Storage.open(path))
        return self

    def _act(self, method: str, **args: Any) -> Action:
        """给**存储角色**组一个动作（用对象身份：ID 与对象两条路都通）。"""
        return Action(role_obj=self.storage, call_function=method, call_args=args)


def _raise_if_failed(outcome: Outcome, doing: str) -> None:
    """引擎把机制性失败记进 `Step.error`；此处把首个失败**显式抛出**。

    抛出的是原异常（不是包一层新类型），调用方按类型捕获仍然有效；
    ``ok`` 为真即无失败。
    """
    if outcome.ok:
        return
    failed = outcome.failed[0]
    error = failed.error
    if error is None:  # 理论上不会发生：ok 为假即至少一步有 error
        raise CairnError(f"{doing}失败：{failed.action.call_function}")
    raise error


def _forget(table: dict[str, dict[Any, object]], obj: object) -> None:
    """把对象从表的三种身份格里摘净（注销 / 换挂件时用）。"""
    for cells in table.values():
        for key, value in list(cells.items()):
            if value is obj:
                cells.pop(key, None)


def _store(table: dict[str, dict[Any, object]], obj: object, *, oid: str, name: str) -> None:
    """按三种身份登记：ID / 名称 / 对象。

    没有 ID 的对象**不登记 ID 格**：空字符串键会让多个无 ID 对象挤在同一格互相覆盖。
    """
    obj_id = str(oid or getattr(obj, "id", "") or "")
    if obj_id:
        table["role_id"][obj_id] = obj
    table["role_name"][str(name or getattr(obj, "name", "") or getattr(obj, "__name__", ""))] = obj
    table["role_obj"][identity_key("role_obj", obj)] = obj


class Managed:
    """**受内核管辖的对象基类**：继承即登记，不用自己管注册。

    为什么**不直接继承 `Core`**：`Core` 是**单例**，一旦被领域对象继承，
    ``Note("01A")`` 会返回内核自己（`__new__` 抢走构造）。两者必须分开：
    `Core` = 单例内核；`Managed` = "我受内核管辖"这件事。

    少数对象（或运行期创建的实例）仍可手动 `core.register(obj, oid=..., name=...)`。
    """

    name = ""

    def __init__(self, core: Core | None = None) -> None:
        """接内核：对象一出生就拿到内核，``self.core.put(...)`` 即可落盘。

        域服务在这里**按自己的名字登记实例**（``name = "note"`` → ``core.role("note")``）。
        只认**本类自己声明**的 ``name``（``type(self).__dict__``）：继承来的名字会让
        子类实例冒名顶替父类的登记。
        """
        self.core = core if core is not None else Core()
        declared = str(type(self).__dict__.get("name", ""))
        if declared:
            self.core.register(self, name=declared)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """**子类定义时**由父类替它登记。

        只有**域服务**（自报短名 ``name``）进最小类型表的 ``domain`` 角色；
        数据类（``Block`` 子类）归 ``data`` 角色，由数据类自己那条链登记——两类不得混同。

        名字取 ``cls.__dict__``（**本类自己声明**的），不是 ``getattr``：否则子类会
        继承父类的 ``name``，把父类在类型表里的登记静默改写成子类。
        """
        super().__init_subclass__(**kwargs)
        Core._types[cls.__name__] = cls  # noqa: SLF001 — 登记口是内核的私有收成
        declared = str(cls.__dict__.get("name", ""))
        if declared != "":
            Core._types[declared] = cls  # noqa: SLF001
            Core.register_type(cls)


__all__ = ["Core", "Managed"]
