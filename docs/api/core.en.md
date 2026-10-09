<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- translation-source-hash: 880b95088b7d1fc8c8b5233a4610ff67d06ad85f714c3930e0e0431662ce4c46 -->
# core (base)

L0: Kernel—**event engine, storage engine, configuration engine, exception layer**, as well as the component that integrates them;
There is also a command plane that is independent of the transport layer. **Red line: Qt-free, transport-independent.**

## Package Entry Point

::: core
    options:
      members: false

## Kernel Assembly

The assembly point of the library, storage engine, and event bus: library switch (on/off), `bind(engine)`,
Failure hook logs. Both writing and reading are initiated by the block itself (`block.save()`/`Note.fetch(identity)`).
There are no longer methods of the `store` / `load` type in the assembly area.

::: core.init

## Configure the Engine

Statement is fact: **The engine is the upstream library OnConf** (PyPI `onconf`), `core.conf` which only handles assembly—fixed configuration root.
(`CAIRN_CONFIG`)+Disable console log output; the engine’s own logging mechanism is used instead. The stored parameters are managed by the storage component itself.
Declaration (`core/storage/conf.py`), the kernel's own line is at `core/params.py`. See semantics and differences.
6.

::: core.conf

::: core.params

::: core.storage.conf

## Event Engine

An event is an **instantaneous notification**: it is not stored and does not carry business workflow; the bus only performs fan-out and does not make decisions.
The directory contains only two entries (`object.put`/`object.deleted`).

::: core.event
    options:
      members: false

::: core.event.events

::: core.event.bus

::: core.event.catalog

## Storage Engine

Each of the four layers manages the layer below it: segment arithmetic and identity (`core.storage.db.id`), carrier, hub, block.↔Slot. A block is divided into attribute slots and content slots.
After the file is written to disk, when an event occurs, deleting it will also remove that line from the index database.

::: core.storage
    options:
      members: false

::: core.storage.engine

::: core.storage.types

::: core.storage.pack

::: core.storage.hub

## Database Engines and Indexes

The library’s structure has only one entry point: **ID**—one type, one identity table (column = `ID_FIELDS`).
In addition, `hub` registration and `meta`. Two types of index blocks **directly inherit** and each has its own identity table.
Only declare `manages` and `holds`; the forward table's payload is stored in index blocks, while the reverse table is computed on-the-fly during reads.

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

## Command Line

Method table of the kernel command interface (seven methods: `tables` / `hubs` / `rows` / `locate` / `record` / `stats` / `delete`):
For the sidecar/CLI/testing purposes, it is transport-agnostic and does not contain any UI code. The payload is submitted in base64 format; the payload's domain is not decoded.

::: core.api

## Exceptions and Time

Exceptions are a layer of declarations (with the caller performing type-based dispatch); time is standardized across the entire database.

::: core.exc

::: core.clock
