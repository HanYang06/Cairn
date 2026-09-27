# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""索引库表声明的**出厂初值**（人被生成物绊住时的兜底）。

配置是本体：`config/settings/core/storage/conf.json` 的 ``storage.db.tables`` 才是**可改的那一份**。
本模块只提供"这项被删掉时补回来的初值"，形状与配置**逐字一致**——
故它读起来就是配置该长的样子，不必再去读解析代码。

为什么单独一个模块：`core/storage/conf.py` 要引用它来登记默认值，而
`core/storage/tables.py` 的解析器要**运行时**读配置——放一起会绕成循环导入。
"""

from __future__ import annotations

from typing import Any

DEFAULT_TABLES: list[dict[str, Any]] = [
    {
        "name": "bucket",
        "doc": "桶登记：桶目录是存在证明，本表是登记",
        "tier": "tier1",
        "owner": "core",
        "rebuild_from": "桶目录：扫 vault 下的桶目录",
        "columns": [
            {"name": "name", "type": "text", "primary_key": True, "doc": "桶名（即目录名）"},
            {
                "name": "role",
                "type": "text",
                "default": "main",
                "doc": "形态：主/归档/临时",
                "not_null": True,
            },
            {
                "name": "state",
                "type": "text",
                "default": "mounted",
                "doc": "挂载状态",
                "not_null": True,
            },
            {
                "name": "created",
                "type": "integer",
                "default": 0,
                "doc": "建立时刻",
                "not_null": True,
            },
        ],
    },
    {
        "name": "record",
        "doc": "身份到位置：一行一条记录（块记录与内容记录同表）",
        "tier": "tier1",
        "owner": "core",
        "rebuild_from": "载体：顺扫全部记录，读记录头重建",
        "columns": [
            {"name": "value_uuid", "type": "text", "primary_key": True, "doc": "分配形态凭证"},
            {
                "name": "value_hash",
                "type": "text",
                "doc": "摘要形态凭证（指向内容）",
                "not_null": True,
            },
            {
                "name": "kind",
                "type": "text",
                "default": "",
                "doc": "类型名（由程序给出）",
                "not_null": True,
            },
            {"name": "bucket", "type": "text", "default": "", "doc": "所在桶", "not_null": True},
            {"name": "pack", "type": "text", "default": "", "doc": "所在载体名", "not_null": True},
            {
                "name": "slot_start",
                "type": "integer",
                "default": 0,
                "doc": "起始槽",
                "not_null": True,
            },
            {
                "name": "slot_head",
                "type": "integer",
                "default": 0,
                "doc": "槽内偏移",
                "not_null": True,
            },
            {
                "name": "slot_count",
                "type": "integer",
                "default": 1,
                "doc": "跨槽数",
                "not_null": True,
            },
            {
                "name": "size",
                "type": "integer",
                "default": 0,
                "doc": "记录字节数",
                "not_null": True,
            },
            {
                "name": "issued",
                "type": "integer",
                "default": 0,
                "doc": "ID 签发时刻",
                "not_null": True,
            },
            {
                "name": "created",
                "type": "integer",
                "default": 0,
                "doc": "落盘时刻",
                "not_null": True,
            },
            {
                "name": "updated",
                "type": "integer",
                "default": 0,
                "doc": "最近写入时刻",
                "not_null": True,
            },
        ],
        "indexes": [
            {"columns": ["value_hash"], "doc": "地址反查：这份内容被哪些记录引用"},
            {"columns": ["kind"], "doc": "按类型筛选"},
            {"columns": ["bucket", "pack"], "doc": "按载体归拢"},
            {"columns": ["updated"], "doc": "按时间排序"},
        ],
    },
    {
        "name": "edge",
        "doc": "关系边：一等行，src --kind--> dst",
        "tier": "tier1",
        "owner": "core",
        "rebuild_from": "块记录：关系数据落在块内时由其派生",
        "columns": [
            {"name": "id", "type": "text", "primary_key": True, "doc": "边身份（由四元组算摘要）"},
            {"name": "src", "type": "text", "doc": "源身份", "not_null": True},
            {"name": "dst", "type": "text", "doc": "目标身份", "not_null": True},
            {"name": "kind", "type": "text", "default": "", "doc": "关系种类", "not_null": True},
            {"name": "domain", "type": "text", "default": "", "doc": "归属域", "not_null": True},
            {
                "name": "created",
                "type": "integer",
                "default": 0,
                "doc": "建立时刻",
                "not_null": True,
            },
        ],
        "indexes": [
            {"columns": ["src", "kind"], "doc": "出边（正向遍历）"},
            {"columns": ["dst", "kind"], "doc": "入边（反查 / backlinks）"},
        ],
    },
]

__all__ = ["DEFAULT_TABLES"]
