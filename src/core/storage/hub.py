# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""hub：一个目录，装若干载体（旧称"桶"，2026-09-29 起统一叫 hub）。

本层管的是"记录落在哪个文件的哪几格"，四条来自设计篇 §6/§7 的约定：

- **判据是形状而不是"是个目录"**：`vault/<hub>/packs/` 才算 hub。库里还会有别的东西，
  见目录就当 hub 会把它们卷进来；`packs/` 里混着不是载体的文件同样报错——
  不把"看不懂的东西"当成不存在（跳过是巡检的策略，不是本层）。
- **读路径不建 hub**：目录不在就报错，绝不悄悄建一个空 hub 顶上——那会把"数据没了"
  伪装成"这里本来就是空的"。建立是显式动作（:meth:`Hub.create`）。
- **hub 无状态、无自己的配置**：槽长随载体走（写进文件头），封口线是每次写入按当前值判的策略。
  故这一层拷到哪里都成立，索引库丢了也能顺扫回来。
- **活跃载体＝有空间的最满者**，一个都没有就新开一个（设计篇 §5.4）。写入纪律是"写到满才换"，
  故这个判据不依赖时间戳、也不依赖载体名顺序（名字是随机串，无顺序语义）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from core.exc import HubNotFoundError, HubShapeError, RecordFormatError, SlotError

from .carrier import Carrier, SlotRange

if TYPE_CHECKING:
    from collections.abc import Iterator

PACKS_DIRNAME = "packs"
"""载体所在的子目录名；它同时是"这个目录是不是 hub"的判据。"""

DEFAULT_SLOT_BYTES = 512
"""默认槽长：两数格模型下一条记录至少占一格，故这个值要小（设计篇 §5.6 的旧值 64 KiB 待回写）。"""

DEFAULT_MAX_BYTES = 2 * 1024**3
"""默认封口线（2 GiB）：只决定"什么时候换文件"，不构成写入的硬上限。"""


@dataclass(frozen=True, slots=True)
class PackPolicy:
    """写载体的策略：槽长与封口线。

    它是**上层传进来的参数，不是配置**——hub 不落盘自己的配置（§6）；同一个 vault 里
    既有载体的槽长一律以各自文件头为准，这份策略只决定**新开载体**怎么写。

    Attributes:
        slot_bytes: 新建载体的槽长；两数格模型下一条记录至少占一格，故这个值要小。
        max_bytes: 封口线；只管"什么时候换文件"，不构成写入的硬上限。
    """

    slot_bytes: int = DEFAULT_SLOT_BYTES
    max_bytes: int = DEFAULT_MAX_BYTES


@dataclass(frozen=True, slots=True)
class Placement:
    """一条记录落在哪儿：载体名 ＋ 格区间。

    这就是上层要的全部定位信息：先按 ``pack`` 开载体，再按 ``span`` 读那几格。

    Attributes:
        pack: 载体文件名（随机串，无语义）。
        span: 该记录在载体里占的格区间。
    """

    pack: str
    span: SlotRange


class Hub:
    """一个 hub 目录：列出载体、挑活跃载体写入、按位置读回、顺扫全部记录。

    构造即校验形状（**不建目录**）；要新建用 :meth:`Hub.create`。
    槽长与封口线是上层传进来的**策略参数**，不是 hub 自己的配置——本层不把它们落盘。
    """

    def __init__(
        self,
        path: str | Path,
        *,
        slot_bytes: int = DEFAULT_SLOT_BYTES,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        """打开一个既有的 hub。

        Args:
            path: hub 目录。
            slot_bytes: 新建载体时的槽长（既有载体一律以各自文件头为准）。
            max_bytes: 封口线。

        Raises:
            HubNotFoundError: 目录不存在。
            HubShapeError: 目录存在但不是 hub 的形状（缺 `packs/`）。
            SlotError: 策略参数不合法。
        """
        self._path = Path(path)
        self._packs = self._path / PACKS_DIRNAME
        if not self._path.is_dir():
            raise HubNotFoundError(f"hub 目录不存在: {self._path}")
        if not self._packs.is_dir():
            raise HubShapeError(f"不是 hub 的形状（缺 {PACKS_DIRNAME}/）: {self._path}")
        self._slot_bytes = _check_positive(slot_bytes, "槽长")
        self._max_bytes = _check_positive(max_bytes, "封口线")

    @classmethod
    def create(
        cls,
        path: str | Path,
        *,
        slot_bytes: int = DEFAULT_SLOT_BYTES,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> Hub:
        """显式建立一个 hub（连同 `packs/`），如同参数打开它。

        建立只在写路径上发生；读路径一律走构造，目录不在就报错。
        """
        directory = Path(path)
        try:
            (directory / PACKS_DIRNAME).mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise HubShapeError(f"无法建立 hub: {directory}（路径上已有同名文件？）") from error
        return cls(directory, slot_bytes=slot_bytes, max_bytes=max_bytes)

    @property
    def path(self) -> Path:
        """Hub 目录。"""
        return self._path

    @property
    def name(self) -> str:
        """Hub 名：目录名就是它的地址（进 ID 的 `in_hub`）。"""
        return self._path.name

    @property
    def packs_dir(self) -> Path:
        """载体所在目录。"""
        return self._packs

    def pack_names(self) -> tuple[str, ...]:
        """全部载体名，按名字排序。

        排序只为让诊断与测试有确定的顺序；**名字本身是随机串，不含顺序语义**。
        """
        return tuple(sorted(entry.name for entry in self._packs.iterdir() if entry.is_file()))

    def append(self, raw: bytes) -> Placement:
        """写入一条记录，返回它的位置。

        放进"有空间的最满者"；一个都没有（或全已封口）就新开一个载体。
        **不检查封口线对单条记录的大小限制**：大于封口线的记录照样完整写入（§5.4）。

        Raises:
            RecordFormatError: 记录不自框定，或选中的载体尾部不在格边界（残写，不猜从哪儿接）。
        """
        for name in self._by_size_desc():
            with self.carrier(name) as carrier:
                if not carrier.sealed(self._max_bytes):
                    return Placement(pack=name, span=carrier.append(raw))
        return self._append_to_new_pack(raw)

    def read(self, placement: Placement) -> bytes:
        """按位置读回一条记录的原始字节（不做解码，解码是记录层的事）。"""
        with self.carrier(placement.pack) as carrier:
            return carrier.read(placement.span)

    def scan(self) -> Iterator[tuple[str, SlotRange, bytes]]:
        """顺扫全部载体的全部记录，交出 ``(载体名, 格区间, 原始字节)``。

        载体自描述、记录自框定，故索引库丢了也能这样重建定位——这是"档一可重建"的底。
        """
        for name in self.pack_names():
            with self.carrier(name) as carrier:
                for span, raw in carrier.scan():
                    yield name, span, raw

    def carrier(self, name: str) -> Carrier:
        """打开一个载体；槽长从它的文件头读，不看当前策略。

        名字不存在即报错——**不建**：载体只在写入时新开（`:meth:`Hub._append_to_new_pack`），
        读一个不存在的名字多半说明位置已经过期，建个空文件只会把问题藏起来。
        """
        target = self._packs / name
        if not target.is_file():
            raise HubNotFoundError(f"载体不存在: {target}")
        try:
            return Carrier(target)
        except (RecordFormatError, SlotError) as error:
            raise HubShapeError(f"{PACKS_DIRNAME}/ 里的 {name} 不是载体: {error}") from error

    def _by_size_desc(self) -> tuple[str, ...]:
        """载体按"从大到小"排；同大小按名字排，使判据完全确定。"""
        sized: list[tuple[int, str]] = []
        for name in self.pack_names():
            with self.carrier(name) as carrier:
                sized.append((carrier.size, name))
        return tuple(name for _size, name in sorted(sized, key=lambda item: (-item[0], item[1])))

    def _append_to_new_pack(self, raw: bytes) -> Placement:
        """新开一个载体，把记录写进去。"""
        name = self._new_pack_name()
        with Carrier(self._packs / name, slot_bytes=self._slot_bytes) as carrier:
            return Placement(pack=name, span=carrier.append(raw))

    def _new_pack_name(self) -> str:
        """取一个还没被占用的随机名：无语义、无顺序号（§5.1）。"""
        while True:
            name = uuid4().hex
            if not (self._packs / name).exists():
                return name


def find_hubs(root: str | Path, *, policy: PackPolicy | None = None) -> tuple[Hub, ...]:
    """列出 root 下形状合规的 hub（带 `packs/` 的直接子目录），按名排序。

    判据是**形状**而不是"是个目录"（§6）：库里还会有别的东西，见目录就当 hub 会把它们卷进来。
    这里只列不改——目录不在就不在结果里，绝不为它建一个。

    Args:
        root: vault 根目录；不存在即返回空（"还没有库"与"库是空的"在这里同义）。
        policy: 打开 hub 时用的策略（只影响将来的写入，不影响列目录）。
    """
    directory = Path(root)
    if not directory.is_dir():
        return ()
    effective = PackPolicy() if policy is None else policy
    return tuple(
        Hub(entry, slot_bytes=effective.slot_bytes, max_bytes=effective.max_bytes)
        for entry in sorted(directory.iterdir(), key=lambda item: item.name)
        if entry.is_dir() and (entry / PACKS_DIRNAME).is_dir()
    )


def _check_positive(value: int, what: str) -> int:
    """正数校验：策略参数不合法就当场拒绝，不带着坏参数跑到写盘那一步。"""
    if value < 1:
        raise SlotError(f"{what}必须为正: {value}")
    return value


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_SLOT_BYTES",
    "PACKS_DIRNAME",
    "Hub",
    "PackPolicy",
    "Placement",
    "find_hubs",
]
