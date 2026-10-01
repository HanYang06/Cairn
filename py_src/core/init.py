# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""内核装配：一个 vault 根加两个引擎。

作者的原初设想（本文件旧稿）是"事件 / 存储 / 配置 / 异常四件事，外加对象管理表与统一日志"。
按 2026-09-29 的裁定，落到实处的只有其中三件，其余两件**不假装存在**：

- **事件引擎**：`Bus`（订阅、按注册顺序投递、异常隔离并交回失败清单）＋ 事件目录；
- **存储引擎**：`Storage`（块落成记录、按身份读回、摘块、落盘后发事件）；
- **异常**：`core.exc` 的层级。它不是"挂载"的东西，内核只把**它与日志接上**——
  `Bus` 的失败钩子就是那条线；
- **配置引擎**不在本层：`src/core/conf/` 由作者另行推进，故 `Kernel` 不装它，也不占位；
- **对象管理表**是**预留**：它要服务的是"按对象收发事件"，而那条路（中介者 / 解析器）已明确不做
  （见 `references/decisions/`「事件层只做扇出通知」），所以现在只把两个引擎挂在属性上，
  不给一个没有调用方的注册表。

约定只在这里定两件事：`root/catalog.db` 是索引库、`root/<hub>/packs/` 是载体；
`open()` 不建东西，`create()` 是显式动作。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Self

from core.conf import conf
from core.event.bus import Bus
from core.storage import tables as _tables
from core.storage.attrindex import build as _build_attrindex
from core.storage.compact import compact as _compact
from core.storage.compact import survey as _survey
from core.storage.conf import PACK_MAX_BYTES, SLOT_BYTES
from core.storage.engine import Storage
from core.storage.hub import PackPolicy
from core.storage.index import Index, RebuildPlan
from core.storage.patrol import patrol as _patrol
from core.storage.patrol import repair as _repair
from core.storage.tablegen import sync as _sync_tables
from core.storage.tables import Declaration, kernel_tables

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from types import TracebackType

    from core.event.events import Event
    from core.storage.attrindex import AttributeIndex
    from core.storage.compact import CompactReport, SurveyReport
    from core.storage.format.id import ID
    from core.storage.patrol import PatrolReport, RepairReport
    from core.storage.rows import BlockRow

CATALOG_FILENAME = "catalog.db"
"""索引库文件名：路径约定只在这里出现一次。"""

LOGGER_NAME = "cairn.kernel"
"""内核日志记录器名：统一日志的入口。"""

SUPERSEDED_TABLES: tuple[str, ...] = ("record", "notediff")
"""更换形状时淘汰的旧表。

- `record`：单表在 2026-09-30 拆成 `block` / `body` 两张；
- `notediff`：笔记的变更记录整体**推迟成预留**（2026-10-01，零调用方），那张表随之淘汰。

写在代码里、名字点明，是为了让"淘汰哪张表"这一动作可见——它不是猜出来的，
而是在这里被人写下的。声明文件里没有这张表时它是空操作。
"""


@dataclass(frozen=True, slots=True)
class _Setup:
    """一次装配的全部输入：声明集、载体策略、重建授权与日志器。"""

    declaration: Declaration
    policy: PackPolicy
    rebuild: RebuildPlan | None
    logger: logging.Logger


def _policy_from_config() -> PackPolicy:
    """默认的载体策略：向配置面要值（默认值只写在 `core/storage/conf.py`，这里不抄第二份）。"""
    return PackPolicy(
        slot_bytes=int(conf(SLOT_BYTES)),
        max_bytes=int(conf(PACK_MAX_BYTES)),
    )


def kernel_declaration(extra: Declaration | None = None) -> Declaration:
    """内核默认声明集：**先让声明文件对上代码，再拿它去开库**。

    这一步是"表会自己诞生"的落点（设计篇 §8.2）：类型登记 → 现算表形状 → 写进
    `config/tables.yaml`（文件不在就整份生成、少表少列就补上、人写的内容一个字不动）
    → 声明文件再被读进库里。于是**手工拆表这件事在流程上没有位置**：类型在，表就在。

    这一步每次装配都跑：它是幂等的，且文件与代码分叉时它能自己收敛回来。
    调用方另外给的声明（领域表）不属于内核那几张，不进声明文件——它们由领域自己走同一条路。

    Args:
        extra: 调用方另外要声明进来的表；不给即只有内核默认那几张。
    """
    # 路径**按模块属性取**，不把这个函数直接绑进本模块：测试夹具拦的是
    # `core.storage.tables.tables_path`，直接导入会让那句 monkeypatch 落空，
    # 于是跑一次用例就把仓根那份入库声明改写掉（已实测发生）。
    _sync_tables(_tables.tables_path(), replace=SUPERSEDED_TABLES)
    base = kernel_tables()
    if extra is None:
        return Declaration(base)
    return Declaration((*base, *extra.extra_tables()))


def _setup(
    declaration: Declaration | None,
    policy: PackPolicy | None,
    rebuild: RebuildPlan | None,
    logger: logging.Logger | None,
) -> _Setup:
    """把可选参数填成默认：声明集缺省由登记表现算，策略与日志器缺省都向自己的声明要。"""
    return _Setup(
        declaration=kernel_declaration(declaration),
        policy=_policy_from_config() if policy is None else policy,
        rebuild=rebuild,
        logger=logging.getLogger(LOGGER_NAME) if logger is None else logger,
    )


class Kernel:
    """内核：一个 vault 根与两个引擎的组装处。

    它只管三件事，多一件都不揽：

    - **库的开关**：路径约定（`catalog.db` 与 `<hub>/packs/`）加上开库 / 建库的区别；
    - **引擎挂载**：事件总线与存储引擎，前者带"处理器抛错 → 记日志"的联动；
    - **维护入口**：巡检与处置从内核进——它们是整库动作，不是某一次写入。

    不作的事也说清：配置引擎不在本层；对象管理表是预留；事件只做通知、不做决策
    （内核里没有解析器，命令路径走显式调用）。
    """

    def __init__(
        self,
        root: Path,
        index: Index,
        bus: Bus,
        policy: PackPolicy,
        logger: logging.Logger,
    ) -> None:
        """由 :meth:`open` / :meth:`create` 使用；不留公开构造。"""
        self._root = root
        self._index = index
        self._bus = bus
        self._policy = policy
        self._logger = logger
        self._storage = Storage(index, root, policy=policy, bus=bus)

    @classmethod
    def create(
        cls,
        root: str | Path,
        *,
        declaration: Declaration | None = None,
        policy: PackPolicy | None = None,
        rebuild: RebuildPlan | None = None,
        logger: logging.Logger | None = None,
    ) -> Kernel:
        """显式建一个 vault（库根 ＋ 索引库），并装配内核。

        Args:
            root: vault 根目录；不存在即建。
            declaration: 表声明集；不给即用内核三表。
            policy: 写载体的策略（槽长与封口线）。
            rebuild: 破坏性差异的授权。
            logger: 内核日志记录器；不给即用 `cairn.kernel`。
        """
        directory = Path(root)
        directory.mkdir(parents=True, exist_ok=True)
        return cls._assemble(directory, _setup(declaration, policy, rebuild, logger), create=True)

    @classmethod
    def open(
        cls,
        root: str | Path,
        *,
        declaration: Declaration | None = None,
        policy: PackPolicy | None = None,
        rebuild: RebuildPlan | None = None,
        logger: logging.Logger | None = None,
    ) -> Kernel:
        """开一个既有的 vault。**读路径不建东西**：库不在即报错。

        Raises:
            IndexNotFoundError: 索引库不在。
            IndexSchemaError: 这不是本程序的索引库，或存在未授权的破坏性差异。
        """
        return cls._assemble(Path(root), _setup(declaration, policy, rebuild, logger), create=False)

    @classmethod
    def _assemble(cls, root: Path, setup: _Setup, *, create: bool) -> Kernel:
        """开库、装总线（带失败→日志联动）、拼出内核：两个入口共用的一段。"""
        index = Index.open(
            root / CATALOG_FILENAME,
            setup.declaration,
            create=create,
            rebuild=setup.rebuild,
        )

        def log_failure(event: Event, handler: object, error: Exception) -> None:
            """事件处理器的失败只记日志、不回流发布者：通知层不该影响写入。"""
            setup.logger.warning(
                "事件处理器抛错，已隔离: type=%s subject=%s handler=%s error=%r",
                event.type,
                event.subject,
                getattr(handler, "__qualname__", handler),
                error,
            )

        return cls(root, index, Bus(on_error=log_failure), setup.policy, setup.logger)

    @property
    def root(self) -> Path:
        """库根目录：hub 与索引库都在这下面。"""
        return self._root

    @property
    def catalog_path(self) -> Path:
        """索引库文件路径。"""
        return self._root / CATALOG_FILENAME

    @property
    def index(self) -> Index:
        """索引库（已对齐）。"""
        return self._index

    @property
    def bus(self) -> Bus:
        """事件总线（订阅 / 发布）。"""
        return self._bus

    @property
    def storage(self) -> Storage:
        """存储引擎。"""
        return self._storage

    @property
    def policy(self) -> PackPolicy:
        """写载体的策略。"""
        return self._policy

    @property
    def logger(self) -> logging.Logger:
        """内核日志记录器。"""
        return self._logger

    def store(
        self,
        data: bytes,
        *,
        hub: str | None = None,
        kind: str = "",
        attrs: Mapping[str, object] | None = None,
    ) -> ID:
        """存一个 body，返回**块身份**。

        内核给的是这一个短面：上层要的多半只是"存进去、拿到身份"。更细的（按地址取内容、
        按身份取位置、按块身份取属性）走 :attr:`storage`。

        `attrs` 是块自己声明的属性（`block_attrs(block)` 的产物），编进块记录载荷。
        """
        return self._storage.store(data, hub=hub, kind=kind, attrs=attrs)

    def load(self, value_uuid: str) -> bytes:
        """按身份把 body 读回来。"""
        return self._storage.load(value_uuid)

    def drop(self, value_uuid: str) -> bool:
        """删掉一个块。

        载体是追加写：旧字节删不掉，删除的落法是在载体末尾留一条墓碑（巡检据此不再把它
        报成"缺行"）。空间要等 :meth:`compact` 才真正回收。

        **UI 需求**：删除不可撤销，故**点删除时要确认**；连续删除模式可免确认——
        那时用户已经在"批量清理"的语境里，逐条确认只是阻力。
        """
        return self._storage.drop(value_uuid)

    def locate(self, value_uuid: str) -> BlockRow | None:
        """取一个身份的块行（诊断用）。"""
        return self._storage.locate(value_uuid)

    def patrol(self) -> PatrolReport:
        """巡检整库：只报告，不动库。"""
        return _patrol(self._index, self._root, policy=self._policy)

    def repair(self, report: PatrolReport) -> RepairReport:
        """按巡检报告处置：**只补不删**。"""
        return _repair(self._index, report)

    def reindex(self) -> AttributeIndex:
        """重建属性速查表并返回它。

        它是**整份重算**的纯派生：顺扫块，按属性自己声明 `indexed=True` 的那些建倒排。
        不落盘、不进备份、不在写路径上维护——丢了重建即可，故不会有"增量维护漏了一处"
        那种不报错、只查不到的事故。

        **UI 需求**：全库顺扫，耗时随库体量增长；界面应在启动或按需重建时放进后台线程
        并给进度。查表本身是内存操作，随便调。
        """
        return _build_attrindex(self._index, self._root, policy=self._policy)

    def survey(self) -> SurveyReport:
        """勘察整库：算出整理计划与显示用的全部数字（**只读**，一个字节都不动）。

        **UI 需求**：点"整理"之后先跑它，把「发现多少块、当前比率、预计结果比率、
        预计耗时」显示出来；用户确认之后再调 :meth:`compact`。预计耗时由界面按
        `bytes_to_read` / `bytes_to_write` 与自己的实测吞吐换算——内核不猜时间。
        """
        return _survey(self._index, self._root, policy=self._policy)

    def compact(
        self,
        *,
        plan: SurveyReport | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> CompactReport:
        """整理整库：把墓碑、被删记录与没人用的正文真正抹掉，空间回收。

        逐份载体重写，只留活着的东西。它与 :meth:`drop` 是一对：那头留标记，这头清现场。

        Args:
            plan: :meth:`survey` 的结果；不给就现场勘察一遍。计划只用来挑目标，
                每一份仍现读现判，所以勘察之后库又变了也不会弄丢活记录。
            on_progress: 每处理完一份载体报一次，参数是（已完成，总数）。
            should_stop: 每份载体开始之前问一次；返回真即停下，已处理的那几份保持不变。

        **UI 需求**（整库动作，全份见 `core/storage/compact.py`）：

        - 先 :meth:`survey` 拿数字给用户看，确认之后再跑这个；
        - 由上层放进**后台线程**（内核同步；文件 IO 本质阻塞，`asyncio` 帮不上）；
        - 用 `on_progress` 显示进度、用 `should_stop` 支持取消；取消不影响数据完整性。
        """
        return _compact(
            self._index,
            self._root,
            plan=plan,
            policy=self._policy,
            on_progress=on_progress,
            should_stop=should_stop,
        )

    def close(self) -> None:
        """关掉索引库连接。"""
        self._index.close()

    def __enter__(self) -> Self:
        """进入 ``with``：内核可用。"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """退出 ``with``：无论是否异常都关库。"""
        self.close()


__all__ = ["CATALOG_FILENAME", "LOGGER_NAME", "Kernel"]
