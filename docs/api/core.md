<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# core（底座）

> L0：内核——**事件引擎 + 存储引擎 + 配置引擎 + 异常层**，以及把它们装在一起的 `Kernel`；
> 另有传输无关的命令面。**红线：Qt-free、传输无关。**

## 包入口

::: core
    options:
      members: false

## 内核装配

库根 ＋ 存储引擎 ＋ 事件总线的装配处：库的开关（`create` / `open`）、`bind(engine)`、
失败钩子接日志。**写与读都由块自己发起**（`block.save()` / `Note.fetch(identity)`），
装配处不再有 `store` / `load` 一类方法。

::: core.init

## 配置引擎

声明即事实：声明时校验、取值时给类型判据。存储的参数由存储自己声明（`core/storage/conf.py`），
配置端只负责展开与取值。

::: core.conf

::: core.storage.conf

## 事件引擎

事件是**瞬时通知**：不进存储、不承载业务流转；总线只做扇出，不做决策。
目录只有两条（`object.put` / `object.deleted`）。

::: core.event
    options:
      members: false

::: core.event.events

::: core.event.bus

::: core.event.catalog

## 存储引擎

四层各管下一层：格算术、载体、hub、块 ↔ 记录。块落成两条记录（内容记录 ＋ 块记录），
落盘后发事件，删除落一条墓碑。

::: core.storage
    options:
      members: false

::: core.storage.engine

::: core.storage.types

::: core.storage.slot

::: core.storage.pack

::: core.storage.hub

## 数据库引擎与索引

库的结构只有一条来路：**ID**——一个类型一张身份表（列 ＝ `ID_FIELDS`），
外加 `hub` 登记与 `meta`。两类索引块**直接继承 `Block`**、各有自己的身份表，
只声明 `manages` 与 `holds`；正表存在索引块的载荷里，反表在读的时候现算。

::: core.storage.db
    options:
      members: false

::: core.storage.db.id

::: core.storage.db.payload

::: core.storage.db.engine

::: core.storage.index
    options:
      members: false

::: core.storage.index.index

::: core.storage.index.attrindex

::: core.storage.index.bodyindex

## 命令面

内核命令面的方法表（七个：`tables` / `hubs` / `rows` / `locate` / `record` / `stats` / `delete`）：
给边车 / CLI / 测试用，传输无关、不含界面代码。载荷原文以 base64 交出，**不解领域载荷**。

::: core.api

## 异常与时间

异常是一层声明（调用方按类型分流）；时间是全库统一的口径。

::: core.exc

::: core.clock
