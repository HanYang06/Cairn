# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""领域测试的夹具：把被别处清掉的类型补回登记表。

**为什么需要**：登记表是**进程级**的，而类型是在**模块 import 时**登记的
（"类型定义即登记"）。`core` 那几支用例有自己的 `clean_registry` 夹具，会把登记表
清空重装成只有 `Body` / `Block`；等轮到本目录，领域类型不会自己回来——模块已经
import 过，类定义不会再执行第二遍。故此处每个用例前把缺的补上，测试与执行顺序无关。
"""

from __future__ import annotations

import pytest

from core.storage.format.block import Block, Body, register_type
from core.storage.registry import REGISTRY
from model.note.types import NoteAsset, NoteData, NoteDiff, NoteGroup, NoteTag

_BASES = (Body, Block)
_CARRIERS = (NoteData, NoteTag, NoteGroup, NoteAsset, NoteDiff)


@pytest.fixture(autouse=True)
def types_are_back_in_the_registry() -> None:
    """缺哪个补哪个：登记按名字幂等，已在的不重复登记。

    两个基底先补——载体的表形状要问它们（指向 `body` 那两列就是从基底推出来的）。
    """
    for base in (*_BASES, *_CARRIERS):
        if REGISTRY.get(base.__name__) is None:
            register_type(base)
