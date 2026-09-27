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
| `storage.pack.max_bytes` | `integer` | `2147483648` | 单个载体的字节上限，写满即封口（只管封口线，不定槽长） | `core.storage.conf.StorageConf` |
| `storage.pack.slot_bytes` | `integer` | `65536` | 槽长：载体内的定长分配与定位单位，建载体时写进文件头 | `core.storage.conf.StorageConf` |
| `storage.tables.declared` | `string` | `{"storage.table.bucket":{"columns":[["created","integer",false,true,false,"0"],["name","text",true,true,false,""],["role","text",false,true,false,"'main'"],["state","text",false,true,false,"'mounted'"]],"doc":"桶登记：桶目录是存在证明，本表是登记","indexes":[],"name":"bucket","rebuild_from":"桶目录：扫 vault 下的桶目录","tier":"tier1"},"storage.table.edge":{"columns":[["created","integer",false,true,false,"0"],["domain","text",false,true,false,"''"],["dst","text",false,true,false,""],["id","text",true,true,false,""],["kind","text",false,true,false,"''"],["src","text",false,true,false,""]],"doc":"关系边：一等行，src --kind--> dst","indexes":[[["dst","kind"],false],[["src","kind"],false]],"name":"edge","rebuild_from":"块记录：关系数据落在块内时由其派生","tier":"tier1"},"storage.table.record":{"columns":[["body_addr","text",false,true,false,"''"],["bucket","text",false,true,false,"''"],["created","integer",false,true,false,"0"],["issued","integer",false,true,false,"0"],["kind","text",false,true,false,"''"],["pack","text",false,true,false,"''"],["size","integer",false,true,false,"0"],["slot_count","integer",false,true,false,"1"],["slot_head","integer",false,true,false,"0"],["slot_start","integer",false,true,false,"0"],["updated","integer",false,true,false,"0"],["value_hash","text",false,true,false,""],["value_uuid","text",true,true,false,""]],"doc":"身份到位置：一行一条记录（含块记录与内容记录）","indexes":[[["bucket","pack"],false],[["kind"],false],[["updated"],false],[["value_hash"],false]],"name":"record","rebuild_from":"载体：顺扫全部记录，读记录头重建","tier":"tier1"}}` | 表声明的规范化投影（生成物：由 core/storage/tables.py 的声明算出，勿手改） | `core.storage.conf.StorageConf` |

## 另见

- 用法契约与两个投影的由来：[配置引擎](../architecture/config.md)
- 值文件与词表分别落在 `config/<hub>/…` 与 `schema/<hub>/…`；总词表是 `schema/settings.json`。
- 格式版本号（`CATALOG_VERSION` / `BLOCK_VERSION` 这类改了会坏库的）**故意不进配置**，留在实现处。
- 想加一条配置：在**用到它的那个包**里声明（例：`src/core/storage/conf.py`），
  然后跑 `uv run python tools/gen_conf.py` 与 `uv run python tools/docgen.py --write`。
