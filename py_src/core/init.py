# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""内核装配：一个库根、一个存储引擎、一条事件总线。

**内核只做"接上一根线"这件事**。存储与索引都在 `core.storage/` 里各自成立，块自己会
`save()` / `fetch()`；故装配处要办的只有三样：

- **路径约定**：库根之下哪儿是索引库（`catalog.db`）、哪儿是载体（`<hub>/packs/`）。
  这两条只在 `core/storage/` 里各写一次，本模块不抄第二份；
- **把能力接上**：`bind(engine)` 之后 `Block.save()` 才有地方落盘。**一个进程一根线**，
  故内核关掉时把它解开；
- **把失败接上**：事件总线的失败钩子接日志——通知层出岔子不该影响写路径。

不在本层的事也说清：配置引擎在 `core/conf/`（谁要配置谁声明）；库的结构由 ID 决定，
不由文件声明；事件只做通知、不做决策（内核里没有解析器）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Self

from core.event.bus import Bus
from core.exc import HubNotFoundError
from core.storage.engine import CATALOG_FILENAME, Engine, bind

if TYPE_CHECKING:
    from types import TracebackType

    from core.event.events import Event

LOGGER_NAME = "cairn.kernel"
"""内核日志记录器名：统一日志的入口。"""


class Kernel:
    """内核：库根、存储引擎与事件总线挂在一起的组装处。

    用法是两句话：

        kernel = Kernel.create(root)      # 建库（显式动作）
        kernel = Kernel.open(root)        # 开既有库（读路径不建东西）

    装配之后 `Block` 就有了落点：`note.save()` / `Note.fetch(identity)` 都经 :attr:`engine`。
    关掉它（或 `with` 退出）会解绑这条线——**一个进程只接一个引擎**。
    """

    def __init__(self, root: Path, engine: Engine, bus: Bus, logger: logging.Logger) -> None:
        """由 :meth:`create` / :meth:`open` 使用；不留公开构造。"""
        self._root = root
        self._engine = engine
        self._bus = bus
        self._logger = logger

    @classmethod
    def create(cls, root: str | Path, *, logger: logging.Logger | None = None) -> Kernel:
        """显式建一个库：造库根，并装配内核。

        **建的是目录，不是索引库**：索引库由引擎在第一次真正要用它时开出来，
        故"只想写载体"的场合不会凭空多出一个库文件。

        Args:
            root: 库根目录；不存在即建。
            logger: 内核日志记录器；不给即用 `cairn.kernel`。
        """
        directory = Path(root)
        directory.mkdir(parents=True, exist_ok=True)
        return cls._assemble(directory, logger)

    @classmethod
    def open(cls, root: str | Path, *, logger: logging.Logger | None = None) -> Kernel:
        """开一个既有的库。**读路径不建东西**：库根不在即报错。

        Raises:
            HubNotFoundError: 库根目录不在。
        """
        directory = Path(root)
        if not directory.is_dir():
            raise HubNotFoundError(f"库根不在: {directory}")
        return cls._assemble(directory, logger)

    @classmethod
    def _assemble(cls, root: Path, logger: logging.Logger | None) -> Kernel:
        """装总线（带失败 → 日志联动）、造引擎、接线：两个入口共用的一段。"""
        resolved = logging.getLogger(LOGGER_NAME) if logger is None else logger

        def log_failure(event: Event, handler: object, error: Exception) -> None:
            """事件处理器的失败只记日志、不回流发布者：通知层不该影响写入。"""
            resolved.warning(
                "事件处理器抛错，已隔离: type=%s subject=%s handler=%s error=%r",
                event.type,
                event.subject,
                getattr(handler, "__qualname__", handler),
                error,
            )

        bus = Bus(on_error=log_failure)
        engine = Engine(root, bus=bus)
        bind(engine)
        return cls(root, engine, bus, resolved)

    @property
    def root(self) -> Path:
        """库根目录：hub 与索引库都在这下面。"""
        return self._root

    @property
    def catalog_path(self) -> Path:
        """索引库文件路径。"""
        return self._root / CATALOG_FILENAME

    @property
    def engine(self) -> Engine:
        """存储引擎：块与记录的读写面。"""
        return self._engine

    @property
    def bus(self) -> Bus:
        """事件总线：订阅 / 发布。写路径发的那两条事件挂在这里。"""
        return self._bus

    @property
    def logger(self) -> logging.Logger:
        """内核日志记录器（事件处理器失败就写到它上面）。"""
        return self._logger

    def close(self) -> None:
        """关掉引擎手里的资源，并**解开那根线**：关掉之后 `save()` 会当场报错。"""
        self._engine.close()
        bind(None)

    def __enter__(self) -> Self:
        """进入 ``with``：内核可用。"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """退出 ``with``：无论是否异常都关库并解绑。"""
        self.close()


__all__ = ["LOGGER_NAME", "Kernel"]
