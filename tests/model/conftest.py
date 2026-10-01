# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""领域测试的夹具：把被别处清掉的类型补回登记表。

**为什么需要**：登记表是**进程级**的，而形状是**探一下 ``__init__``** 才有的；
``core`` 那几支用例有自己的夹具，会把登记表整份清空并只装回内核那两张表。
等轮到本目录，领域类型不会自己回来——它们的探针连同登记一起被清掉了。
故此处每个用例前把内核表装回、再把领域类逐个重新接管；测试因此与执行顺序无关。
"""

from __future__ import annotations

import pytest

from core.storage.format.block import adopt, install_core_types
from core.storage.registry import REGISTRY
from model.note.types import NoteAsset, NoteCanvas, NoteData, NoteGroup, NoteTag

_CARRIERS = (NoteData, NoteTag, NoteGroup, NoteAsset, NoteCanvas)


@pytest.fixture(autouse=True)
def types_are_back_in_the_registry() -> None:
    """缺哪张内核表补哪张，再把五个领域类重新接管一次（`adopt` 自己幂等）。"""
    if REGISTRY.get("Block") is None:
        install_core_types()
    for carrier in _CARRIERS:
        adopt(carrier)
