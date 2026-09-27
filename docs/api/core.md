<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# core（底座）

> L0：内核（配置引擎 + 信号引擎 + 存储 + 类型地基）。
> **必须 Qt-free、传输无关** —— 这条是硬红线。

## 包入口

对外只有这几样（`core/__init__.py` 的 `__all__`）：

::: core
    options:
      members: false

## 内核本体

两张对象表 + 引擎挂载点 + 最短调用面。

::: core.core

## 信号引擎

解析 `Event` 包，按包内字段解析到实际角色，形成有效动作。

::: core.signal

## 存储

块 / 桶 / 载体 / 索引库，以及它的引擎角色（不认识领域语义）。
**实现细节按 `_` 前缀过滤；`storage-design.md` 是这一层的唯一事实来源。**

::: core.storage

## 配置引擎

声明即事实：`Cfg` 写在声明模块的类体里，绑上即报到，展开出「值」与「词表」两个投影落盘。

::: core.conf

## 类型地基

错误、标识符、类型表、标注（`Attr` / `Data` / `Cfg`）、事件数据结构。

::: core.types
