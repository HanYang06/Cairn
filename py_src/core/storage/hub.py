# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""hub:一个目录,装若干载体.

它是**写入路径上"选地方"的那一层**,按分工只做三件事:

- **挑活跃载体**:有空间的最满者;一个都没有就新开一份;
- **开载体**:按名字取某一份(读侧),或按策略新建一份(写侧);
- **报出全部载体**:顺扫的入口.

**它自己一行字节都不写**——写是 :class:`~core.storage.pack.Pack` 的事,hub 只把请求转过去.
判据很直白:整个存储里只有 `pack.py` 以写方式打开载体文件.

四条约定:

- **判据是形状而不是"是个目录"**:`<hub>/packs/` 才算 hub.vault 下还会有别的东西,
  见目录就当 hub 会把它们卷进来;`packs/` 里混着不是载体的文件同样报错——不把"看不懂的东西"
  当成不存在;
- **读路径不建 hub**:目录不在即报错,绝不悄悄建一个空的顶上——那会把"数据没了"伪装成
  "这里本来就是空的".建立是显式动作(:meth:`Hub.create`);
- **hub 无状态,无自己的配置**:格长随载体走(写在文件头里),封口线是每次写入按当前值判的策略.
  故这一层挪到哪儿都成立,它只需要索引库告诉它"活口在哪儿";
- **多 hub 对上层只是一次分组**:引擎只需回答"这个身份在哪个 hub".
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from core.exc import HubNotFoundError, HubShapeError

from .pack import DEFAULT_MAX_BYTES, MAGIC, Pack

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

PACKS_DIRNAME = "packs"
"""载体所在的子目录名。它同时是"这个目录算不算 hub"的判据。"""

DEFAULT_SLOT_BYTES = 512
"""开箱格长（字节）：**构造本层时没给 `slot_bytes` 的退路**。

两档全不写等于零、等于错，故配置面至少要有一档带默认值（那条默认值写在 `storage/conf.py`
的声明处，且必须是**字面量**——OnConf 的静态面认不出常量名）。取最小的一档带它，是因为
**格长要小**：一格装不满就空着，故格长即每槽的平均浪费上限；512 B 是"装得下小字段、又不
浪费大截"的那一档。要更大就往上写 ``kb``——**加一档是加法，不是替换**。

**这个数住在这里**：它是格这一层的构造退路；把它抬进配置声明那份文件会让本模块反过来依赖
配置引擎，而本模块只做算术（读配置是 `storage/conf.py` 的事）。声明处那条是配置的默认值，
两处同值、分叉由 `tests/core/test_conf_projection.py` 拦下。
"""


class Hub:
    """一个 hub 目录:装若干载体,选一个来写.

    它不认识块,不认识身份,不认识索引库——只认识载体文件与格.

    Args:
        directory: hub 目录(`vault/<名>`).
        slot_bytes: 新建载体时写进文件头的格长;**读已有载体不看它**.
        max_bytes: 封口线;只管"什么时候换文件",不是硬上限.
    """

    def __init__(
        self,
        directory: Path,
        *,
        slot_bytes: int = DEFAULT_SLOT_BYTES,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        """接上一个 hub 目录.**不建目录,不建载体**:那是 `create` 与 `new_pack` 的事."""
        self._dir = directory
        self._slot_bytes = slot_bytes
        self._max_bytes = max_bytes

    @classmethod
    def create(
        cls,
        directory: Path,
        *,
        slot_bytes: int = DEFAULT_SLOT_BYTES,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> Hub:
        """**显式建立**一个 hub:造目录与 `packs/`.幂等."""
        (directory / PACKS_DIRNAME).mkdir(parents=True, exist_ok=True)
        return cls(directory, slot_bytes=slot_bytes, max_bytes=max_bytes)

    @classmethod
    def open(
        cls,
        directory: Path,
        *,
        slot_bytes: int = DEFAULT_SLOT_BYTES,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> Hub:
        """打开一个既有的 hub.**读路径不建东西**.

        Raises:
            HubNotFoundError: 目录不在,或它下面没有 `packs/`(形状不符,不当作 hub).
        """
        if not directory.is_dir():
            raise HubNotFoundError(f"hub 目录不在: {directory}")
        if not (directory / PACKS_DIRNAME).is_dir():
            raise HubShapeError(f"这不是 hub（缺 {PACKS_DIRNAME}/）: {directory}")
        return cls(directory, slot_bytes=slot_bytes, max_bytes=max_bytes)

    # ---- 属性 ---- #

    @property
    def directory(self) -> Path:
        """Hub 目录."""
        return self._dir

    @property
    def name(self) -> str:
        """Hub 名:**它就是目录名**,也是身份里 `in_hub` 那一项."""
        return self._dir.name

    @property
    def packs_dir(self) -> Path:
        """载体目录 `<hub>/packs/`."""
        return self._dir / PACKS_DIRNAME

    # ---- 载体清单 ---- #

    def pack_names(self) -> tuple[str, ...]:
        """本 hub 里全部载体的名字,**按名字排序**(名字是随机串,排序只为结果稳定).

        判据是**文件头认不认得出这是载体**,不是"它是不是一个文件":`packs/` 里混进别的东西
        (临时文件,人手工放的说明)即报错.跳过是巡检的策略,不是本层的——本层看见了就说.

        Raises:
            HubShapeError: `packs/` 里混着不是载体的东西(子目录同样算).
        """
        if not self.packs_dir.is_dir():
            raise HubNotFoundError(f"hub 里没有 {PACKS_DIRNAME}/: {self._dir}")
        names: list[str] = []
        for entry in sorted(self.packs_dir.iterdir()):
            if not entry.is_file():
                raise HubShapeError(f"{PACKS_DIRNAME}/ 里混着目录: {entry}")
            if not _is_pack(entry):
                raise HubShapeError(f"{PACKS_DIRNAME}/ 里混着不是载体的文件: {entry}")
            names.append(entry.name)
        return tuple(names)

    def packs(self) -> Iterator[Pack]:
        """逐个打开全部载体(调用方用完即弃)——**顺扫的入口**."""
        for name in self.pack_names():
            yield Pack.open(self.packs_dir / name, max_bytes=self._max_bytes)

    # ---- 选地方 ---- #

    def active(self) -> Pack | None:
        """活跃载体:**有空间的最满者**;一份都没有就是 ``None``.

        写入纪律是"写到满才换",故这个判据不依赖时间戳,也不依赖载体名的顺序——
        名字是随机串,本来就没有顺序语义.封口线调大之后可能不止一份有空间,
        此时按同一判据仍只有一个答案.
        """
        best: Pack | None = None
        for name in self.pack_names():
            pack = Pack.open(self.packs_dir / name, max_bytes=self._max_bytes)
            if pack.sealed:
                continue
            if best is None or pack.size > best.size:
                best = pack
        return best

    def carrier(self, prefer: str | None = None) -> Pack:
        """给一个块挑一份载体:**它自己那一份优先**,否则活跃载体,再否则新开一份.

        **一个块只挑一次**(2026-10-07 裁定):调用方拿到这一份之后,把该块这一次要写的
        全部槽都追加进去,中途不再重挑——故一个块不会跨载体.`prefer` 是块在库里记的那
        一份;**即使它已经封口也照用**:块继续写自己那一份,不叫跨载体;若它不在了
        (被人删掉)则忽略,另挑一份,旧槽由回收收走.

        Args:
            prefer: 块自己那一份载体的名字;不给或不在即另挑.

        Returns:
            这个块这一次要写进去的那一份载体.
        """
        if prefer:
            path = self.packs_dir / prefer
            if path.is_file():
                return Pack.open(path, max_bytes=self._max_bytes)
        pack = self.active()
        if pack is None:
            return self.new_pack()
        return pack

    def new_pack(self) -> Pack:
        """新建一份载体:文件名取一个**无语义的随机串**,其真源是文件系统本身.

        格长与封口线都交给它:新载体照当前策略建,建完才轮到"要不要封口"去判——
        少了封口线这一项,`sealed` 就会拿默认值判,而配置里的那个数**看起来生效,实际没有**.
        """
        return Pack(
            self.packs_dir / uuid4().hex,
            slot_bytes=self._slot_bytes,
            max_bytes=self._max_bytes,
        )

    def pack(self, name: str) -> Pack:
        """按名字取一份载体(读侧).

        Raises:
            HubNotFoundError: 这个名字下没有载体.
        """
        path = self.packs_dir / name
        if not path.is_file():
            raise HubNotFoundError(f"载体不在: {name}（hub {self.name}）")
        return Pack.open(path, max_bytes=self._max_bytes)

    def append(self, kind: int, content: bytes) -> tuple[str, int]:
        """把一个槽追加进本 hub,返回(载体名,槽号).

        hub 只负责"选地方":选完就把请求转给 :meth:`Pack.append`,自己不碰字节.
        **一格天然落在同一份载体上**,故这个方法不涉及"跨不跨"的问题;要一次写好几格
        (一个块)——先用 :meth:`carrier` 挑定那一份,再逐格调 :meth:`Pack.append`.

        **先判再写**:活跃载体封口了就**当场另开一份**,不把这个槽塞进那份满载的.
        若不先判,封口线小到"写一格就满"时,活跃判据会反复挑中同一份,来回摆.
        """
        pack = self.active()
        if pack is None or pack.sealed:
            pack = self.new_pack()
        return pack.name, pack.append(kind, content)

    def __repr__(self) -> str:
        """诊断用:名字与格长,不读盘."""
        return f"Hub(name={self.name!r}, slot={self._slot_bytes})"


def _is_pack(path: Path) -> bool:
    """这个文件认不认得出是载体:**只看魔数**,不解析记录,不报格式错.

    判据交给 hub 是因为"`packs/` 里该有什么"是目录这一层的事;认魔数是最轻的那一问,
    比试着打开它更不容易把"坏载体"误判成"不是载体".
    """
    try:
        return path.read_bytes()[: len(MAGIC)] == MAGIC
    except OSError:
        return False


def find_hubs(root: Path) -> tuple[Hub, ...]:
    """在库根下按**形状**找出全部 hub,按名字排序.

    判据是 `<目录>/packs/` 存在,而不是"是个目录"——库根下还会有别的东西,
    见目录就当 hub 会把它们卷进来.**只找,不建**.
    """
    if not root.is_dir():
        return ()
    found = [
        Hub(entry, max_bytes=DEFAULT_MAX_BYTES)
        for entry in sorted(root.iterdir())
        if entry.is_dir() and (entry / PACKS_DIRNAME).is_dir()
    ]
    return tuple(found)


__all__ = ["DEFAULT_SLOT_BYTES", "PACKS_DIRNAME", "Hub", "find_hubs"]
