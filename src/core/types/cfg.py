# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""``Cfg``：**配置项声明**（工具单元家族里的一员，与 ``Attr`` 同族）。

两件事一起干，所以声明与取值不会是两份东西：

1. **声明即登记**：在类体里当类属性绑上时（``__set_name__``），它向登记表报到——
   路径、类型、默认值、说明、归属（宿主类 / 模块）。声明怎么写，配置就长什么样；
2. **读属性即取值**：``StorageConf.pack_max_blocks`` 读到的就是引擎算出来的值
   （文件里的值 → 默认值），不要求使用方知道文件在哪、叫什么。

默认值的语义（作者 2026-09-26 定）：

- 传了值 → 这条**带值注册**，会展开进 ``config/``；
- 没传值 → 只有 ``schema/`` 里出现，``config/`` 里不呈现，值缺失即报错；
- ``empty_ok=True``（增强写法）→ **哪怕值是空的也按默认处理**（``""`` / ``None`` / ``[]``）。

本模块**只依赖标准库**：它属 ``core.types``（地基），不许反向依赖 ``core.conf`` 引擎。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .errors import CairnError

_MISSING = object()

_logger = logging.getLogger(__name__)


def _is_empty_default(value: Any) -> bool:
    """与引擎的「空值」口径一致（``None`` / 空串 / 空容器；``0`` 与 ``False`` **不算空**）。

    本模块只依赖标准库，故就地判断，不反向引用 ``core.conf`` 引擎。
    """
    if value is _MISSING:
        return False
    if value is None or value == "":
        return True
    return isinstance(value, (list, dict, tuple, set)) and not value


@dataclass(frozen=True, slots=True)
class CfgItem:
    """一条配置声明的**静态描述**（登记表里的事实）。"""

    key: str
    """点分路径（``storage.pack.max_blocks``）。"""

    owner: str
    """宿主类名（给人看）。"""

    module: str
    """宿主类所在模块（决定它展开进哪个文件）。"""

    item: str
    """宿主类里的字段名。"""

    type: Any = None
    """类型提示：可以是普通类，也可以是 ``int | None`` / ``list[int]`` 这类联合与泛型。"""
    default: Any = None
    doc: str = ""
    empty_ok: bool = False
    """``empty_ok=True`` 的增强写法：空值（``None`` / 空串 / 空容器）也按默认处理。"""
    fillable: bool = False
    """是否带值注册（带值才能补进 ``config/``）。"""

    def __post_init__(self) -> None:
        """路径必须是点分形式：空段会让文件归属算不出来。"""
        if not self.key or any(not part for part in self.key.split(".")):
            raise ValueError(f"配置路径非法：{self.key!r}")


_ITEMS: dict[str, CfgItem] = {}


def register(item: CfgItem) -> CfgItem:
    """登记一条配置声明；同一路径重复登记且内容不一致即报错（不静默覆盖）。"""
    found = _ITEMS.get(item.key)
    if found is not None and found != item:
        raise ValueError(f"配置项重复登记且声明不一致：{item.key!r}")
    _ITEMS[item.key] = item
    return item


def items() -> list[CfgItem]:
    """全部声明（按路径排序）。"""
    return [_ITEMS[key] for key in sorted(_ITEMS)]


def item(path: str) -> CfgItem | None:
    """按路径取声明；没登记返回 ``None``。"""
    return _ITEMS.get(path)


def clear() -> None:
    """清空登记表（**给测试隔离用**；产品代码不该调）。"""
    _ITEMS.clear()


class Cfg:
    """配置项声明 / 取值描述符。

    用法::

        class StorageCfg:
            pack_max_blocks: Cfg = Cfg("storage.pack.max_blocks", 4096, doc="单个载体最多装多少块")
            catalog_version: Cfg = Cfg("storage.catalog.version", doc="格式版本：只登记，不给值")

    读到的值由引擎（``core.conf``）算：文件里有 → 文件说了算；文件里没有 → 默认值；
    默认值也没有 → 报错（不猜）。
    """

    def __init__(
        self,
        path: str,
        default: Any = _MISSING,
        *,
        doc: str = "",
        empty_ok: bool = False,
        item_type: Any = None,
    ) -> None:
        if not empty_ok and _is_empty_default(default):
            raise ValueError(
                f"默认值不得为空（会写出读不回来的空值，读的时候按空值报错）：{path!r}；"
                "确实要以空为默认时，显式传 empty_ok=True"
            )
        self.path = path
        self.doc = doc
        self.empty_ok = empty_ok
        self._item_type = item_type
        self.key = path
        self.owner = ""
        self.field = ""
        self.type: Any = None
        self.fillable = default is not _MISSING
        self._default_value = None if default is _MISSING else default
        self._resolved = False

    @classmethod
    def __class_getitem__(cls, item: Any) -> Any:
        """支持文档推荐的 ``Cfg[int]`` **注解**写法：下标即注解里的类型本身。

        只服务注解（``get_type_hints`` 拿到的就是 ``int``，词表照着出类型）；
        若要在这里返回泛型别名，取值面还得再解一层包，得不偿失。
        """
        return item

    # ---- 登记：类体里绑上即报到 ----
    def __set_name__(self, owner: type, name: str) -> None:
        self.key = self.path
        self.owner = owner.__name__
        self.field = name
        self._resolve_type(owner)
        register(
            CfgItem(
                key=self.key,
                owner=self.owner,
                module=owner.__module__,
                item=name,
                type=self.type,
                default=self._default_value,
                doc=self.doc or self._doc_of(owner),
                empty_ok=self.empty_ok,
                fillable=self.fillable,
            )
        )

    def _resolve_type(self, owner: type) -> None:
        """定下这条声明的类型，供词表（schema）使用。

        注解写成 ``Cfg[str]`` 最好（类型就是它）；写裸 ``Cfg`` 时，注解不带信息，
        就**按默认值推**（``4096`` → ``int``）——不猜、只推有把握的。
        **联合与泛型提示同样采纳**（``Cfg[int | None]`` / ``item_type=list[int]``）：
        词表的 `type_schema` 认得它们，若在这里按「必须是 ``type``」筛掉，
        显式传参就被无声吞掉，两条口径还会打架。
        注解解析失败（写错名字之类）只降级并记一条日志：不该因此挡住登记，
        但也不能静默——词表里少一条类型是看得见的差异。
        """
        if self._resolved:
            return
        self._resolved = True
        hint: Any = self._item_type
        if hint is None:
            try:
                from typing import get_type_hints  # noqa: PLC0415 — 仅此处需要

                hint = get_type_hints(owner).get(self.field)
            except (NameError, TypeError, AttributeError) as exc:
                _logger.debug(
                    "注解解析失败，按默认值推类型：%s.%s（%s）", owner.__name__, self.field, exc
                )
                hint = None
        if hint is None or hint is Cfg:
            hint = type(self._default_value) if self.fillable else None
        self.type = hint

    @staticmethod
    def _doc_of(owner: type) -> str:
        """字段说明兜底：类体里那行注释取不到，退而用类 docstring 的首行。

        空白串（``\"\"\"   \"\"\"``）也算「没有 docstring」：先 strip 再取行，
        否则 ``splitlines()`` 出空列表、``[0]`` 会在类体定义期抛 ``IndexError``。
        """
        lines = (owner.__doc__ or "").strip().splitlines()
        return lines[0] if lines else ""

    # ---- 取值：属性访问即向引擎要 ----
    def __get__(self, instance: object, owner: type | None = None) -> Any:
        """读属性 = 向引擎要值。

        只兜住「引擎不可用」（地基被单独加载时读不到落点）这一种预期情况；
        引擎自己的 `ConfigKeyError` / `ConfigValueError` **照原样冒泡**——契约是
        「值缺失即报错、不猜」，吞掉它等于把坏配置伪装成默认值。
        """
        try:
            from core.conf.engine import conf  # noqa: PLC0415 — 延迟导入，避免地基依赖引擎
        except ImportError:  # 引擎没接线：没有取值面，只能给声明里的默认值
            return self._default_value
        return conf.get(self.key)

    def __set__(self, instance: object, value: Any) -> None:
        """赋值 = 写进配置文件（不是写内存字段）——配置只有文件一个真源。

        写路径没有「退回家底」这条路（值必须有落点），故引擎不可用时**显式报错**，
        与读路径的兜底构成明确的不对称：读能给默认值，写不能假装写成功。
        """
        try:
            from core.conf.engine import conf  # noqa: PLC0415
        except ImportError as exc:
            raise CairnError(f"配置引擎不可用，无法写入配置：{self.key}") from exc
        conf.set(self.key, value)

    @property
    def default(self) -> Any:
        """声明里写的默认值（可能为 ``None``：没传值）。"""
        return self._default_value


__all__ = ["Cfg", "CfgItem", "clear", "item", "items", "register"]
