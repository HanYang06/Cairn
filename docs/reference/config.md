<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 配置项参考

!!! danger "本页由工具生成，请勿手改"

    由 `uv run python tools/docgen.py --write` 生成，表来自 **`schema/settings.json`**
    （配置引擎的生成物）。改口径请改生成器，改配置请改声明类；
    `--check` 已进 CI，漂移即失败。**手改这一页会在下一次生成时被抹掉。**

## 怎么读这张表

- **键** = 点分路径，写进 `config/<hub>/…` 的值文件里（用户改过的值永不覆写）。
- **归属** = 该键由哪个声明类定义（`x-cairn-owner`）——**谁用配置谁在自己包里声明**。
- **默认值** = 声明里给的默认；`—` 表示没有默认值（这时键丢了就报错，见下）。

## 取值三条（不猜、不自动修）

| 情形 | 行为 |
|---|---|
| 键在、值空 | **报错** |
| 键丢、有默认值 | **补回来**（只补缺失的键） |
| 键丢、没默认值 | **报错** |

## 全部配置项（5 条）

| 键 | 类型 | 默认值 | 说明 | 归属 |
|---|---|---|---|---|
| `core.log.level` | `string` | `WARNING` | 内核日志级别 | `core.conf.params.CoreConf` |
| `storage.block.max_bytes` | `integer` | `1048576` | 单个块的字节上限，超过即分片（分片 + 索引块） | `core.storage.conf.StorageConf` |
| `storage.db.tables` | `array` | `[{'name': 'bucket', 'doc': '桶登记：桶目录是存在证明，本表是登记', 'tier': 'tier1', 'owner': 'core', 'rebuild_from': '桶目录：扫 vault 下的桶目录', 'columns': [{'name': 'name', 'type': 'text', 'primary_key': True, 'doc': '桶名（即目录名）'}, {'name': 'role', 'type': 'text', 'default': 'main', 'doc': '形态：主/归档/临时', 'not_null': True}, {'name': 'state', 'type': 'text', 'default': 'mounted', 'doc': '挂载状态', 'not_null': True}, {'name': 'created', 'type': 'integer', 'default': 0, 'doc': '建立时刻', 'not_null': True}]}, {'name': 'record', 'doc': '身份到位置：一行一条记录（块记录与内容记录同表）', 'tier': 'tier1', 'owner': 'core', 'rebuild_from': '载体：顺扫全部记录，读记录头重建', 'columns': [{'name': 'value_uuid', 'type': 'text', 'primary_key': True, 'doc': '分配形态凭证'}, {'name': 'value_hash', 'type': 'text', 'doc': '摘要形态凭证（指向内容）', 'not_null': True}, {'name': 'kind', 'type': 'text', 'default': '', 'doc': '类型名（由程序给出）', 'not_null': True}, {'name': 'bucket', 'type': 'text', 'default': '', 'doc': '所在桶', 'not_null': True}, {'name': 'pack', 'type': 'text', 'default': '', 'doc': '所在载体名', 'not_null': True}, {'name': 'slot_start', 'type': 'integer', 'default': 0, 'doc': '起始槽', 'not_null': True}, {'name': 'slot_head', 'type': 'integer', 'default': 0, 'doc': '槽内偏移', 'not_null': True}, {'name': 'slot_count', 'type': 'integer', 'default': 1, 'doc': '跨槽数', 'not_null': True}, {'name': 'size', 'type': 'integer', 'default': 0, 'doc': '记录字节数', 'not_null': True}, {'name': 'issued', 'type': 'integer', 'default': 0, 'doc': 'ID 签发时刻', 'not_null': True}, {'name': 'created', 'type': 'integer', 'default': 0, 'doc': '落盘时刻', 'not_null': True}, {'name': 'updated', 'type': 'integer', 'default': 0, 'doc': '最近写入时刻', 'not_null': True}], 'indexes': [{'columns': ['value_hash'], 'doc': '地址反查：这份内容被哪些记录引用'}, {'columns': ['kind'], 'doc': '按类型筛选'}, {'columns': ['bucket', 'pack'], 'doc': '按载体归拢'}, {'columns': ['updated'], 'doc': '按时间排序'}]}, {'name': 'edge', 'doc': '关系边：一等行，src --kind--> dst', 'tier': 'tier1', 'owner': 'core', 'rebuild_from': '块记录：关系数据落在块内时由其派生', 'columns': [{'name': 'id', 'type': 'text', 'primary_key': True, 'doc': '边身份（由四元组算摘要）'}, {'name': 'src', 'type': 'text', 'doc': '源身份', 'not_null': True}, {'name': 'dst', 'type': 'text', 'doc': '目标身份', 'not_null': True}, {'name': 'kind', 'type': 'text', 'default': '', 'doc': '关系种类', 'not_null': True}, {'name': 'domain', 'type': 'text', 'default': '', 'doc': '归属域', 'not_null': True}, {'name': 'created', 'type': 'integer', 'default': 0, 'doc': '建立时刻', 'not_null': True}], 'indexes': [{'columns': ['src', 'kind'], 'doc': '出边（正向遍历）'}, {'columns': ['dst', 'kind'], 'doc': '入边（反查 / backlinks）'}]}]` | 索引库的表声明（**本体在这**：改它即改表；列项顺序即建表顺序） | `core.storage.conf.StorageConf` |
| `storage.pack.max_bytes` | `integer` | `2147483648` | 单个载体的字节上限，写满即封口（只管封口线，不定槽长） | `core.storage.conf.StorageConf` |
| `storage.pack.slot_bytes` | `integer` | `65536` | 槽长：载体内的定长分配与定位单位，建载体时写进文件头 | `core.storage.conf.StorageConf` |

## 另见

- 用法契约与两个投影的由来：[配置引擎](../architecture/config.md)
- 值文件与词表分别落在 `config/<hub>/…` 与 `schema/<hub>/…`；总词表是 `schema/settings.json`。
- 格式版本号（`CATALOG_VERSION` / `BLOCK_VERSION` 这类改了会坏库的）**故意不进配置**，留在实现处。
- 想加一条配置：在**用到它的那个包**里声明（例：`src/core/storage/conf.py`），
  然后跑 `uv run python tools/gen_conf.py` 与 `uv run python tools/docgen.py --write`。
