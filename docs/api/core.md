<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# core（底座）

> L0：内核——**事件引擎 + 存储引擎 + 异常层**，以及把它们装在一起的 `Kernel`。
> **必须 Qt-free、传输无关** —— 这条是硬红线。

## 包入口

::: core
    options:
      members: false

## 内核装配

一个库根加两个引擎：库的开关、引擎挂载与维护入口（`patrol` / `repair`）。

::: core.init

## 事件引擎

事件是**瞬时通知**：不进存储、不承载业务流转；总线只做扇出，不做决策。

::: core.event
    options:
      members: false

::: core.event.events

::: core.event.bus

::: core.event.catalog

## 存储引擎

块落成记录、按身份读回、摘块，落盘后发事件；hub 是载体所在的那一层目录。

::: core.storage
    options:
      members: false

::: core.storage.engine

::: core.storage.index

::: core.storage.hub

::: core.storage.carrier

::: core.storage.rows

::: core.storage.tables

::: core.storage.patrol

## 字节格式

身份、块载荷与载体记录：落盘字节的定义处，改它们就是改格式。

::: core.storage.format
    options:
      members: false

::: core.storage.format.id

::: core.storage.format.block

::: core.storage.format.record

## 异常与时间

异常是一层声明（调用方按类型分流）；时间是全库统一的口径。

::: core.exc

::: core.clock
