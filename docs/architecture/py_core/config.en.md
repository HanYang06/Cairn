<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- translation-source-hash: 1eda9c8caaaf665de5f0d5f0a05994a8043b841a193defbb6b0ff8339179a33e -->
# Configure the engine

> Status: **Current** (Switched to OnConf on 2026-10-04; will be phased out with OnConf 2.0 on 2026-10-07).
> Source of truth: (**Assembly**: fixed configuration root + controlled console log output), each package's own declarations.
> Modules (A, B), as well as the **upstream library** OnConf
(PyPI name `onconf`, Apache-2.0). This document is the **usage agreement**; the semantics of the engine itself shall be governed by the upstream documentation.
Here, we only record "how the kernel side handles it and where the boundary lies."

## 1. One sentence

**The kernel does not come with a configuration engine, nor does it wrap the engine in a forwarding layer.** Only perform engine **assembly**:
Set the root directory (if not specified, use the one under the warehouse root), and disable console logging.
Both declarations and values must use OnConf's own `conf`:

```python
from onconf import conf

conf("core.storage.pack.max.byte", 2_147_483_648, doc="封口线")  # 声明
ceiling = int(conf("core.storage.pack.max.byte"))  # 取值
```

**Both keys and default values must be literals**: Literals written at the call site constitute the static surface of OnConf (`build` / `sync`/
(2) The only form that can be understood; the reasons and consequences are discussed in §2.

**Assembly must occur before the first `conf()`**: The OnConf engine is a singleton; the bootstrap layer parameters (`home` / `file_name`/
Once a declaration of the first kind is encountered, it cannot be changed, and the declaration of the core occurs during the **import phase**. Therefore
First import `core.conf`, then import the declaration module: **import `core` to complete the assembly**. In the warehouse, declare configurations in this order.
(All declaration modules are under `core`; importing it requires running `core/__init__.py` first.) When the order is reversed, the assembly statement will result in
"The engine has already started" is thrown on the spot, and will not silently fall back to an incorrect configuration root.

## 2. Declaration and Retrieval: Two Modes in a Single Call

| Writing | Meaning |
|---|---|
| `conf("a.b", 默认值, doc=…)` | **Declaration** (Add if missing from the document; otherwise, respect the existing content) |
| `conf("a.b", doc=…)` | Register an item that has **no default value** ⇒ Immediately retrieve its value; if no value is assigned, an error will be reported. |
| `conf("a.b")` | **Value** |

On the parameter side, there are only three options: `key`, `value`, and `doc` (closed starting from version 2.0): whether or not `value` is provided serves as the criterion for determining “write or read.”
(`None` / `0` / `""` all count), add them to the word list for use in IDE hover tooltips and reference pages.

-**Literal only in the declaration**: OnConf’s static surface relies on the AST to recognize “literals at the call site”—both keys and default values must be supported.
If it’s calculated and written as a constant name, an expression (`2 * 1024**3`), or a key constructed within a loop, it won’t be recognized.
**Expectation Set**: Report keys that have already been stored as “undeclared,” and refuse to execute (if the expectation set is incomplete, do not delete the keys).
The value file is rewritten based on the incomplete expectation set. Therefore, on the declaration side, hardcode the key and its default value; on the value-fetching side, continue to use the same literal.
-**One default value, one fallback constructor**: The grid length and the sealing line each have a fallback constructor at the implementation level.
(`hub.DEFAULT_SLOT_BYTES` / `pack.DEFAULT_MAX_BYTES`, use it when no parameters are provided), the one at the declaration is the configuration.
Default; two places are monitored by a single use case from `tests/core/test_conf_projection.py`, and changing one side results in failure;
-**Key names by `<层>.<域>.<对象>.<属性>`**: The layer prefix is consistent with the package where the declaration is located (storing those five groups as `core.storage.`
At the beginning, the declaration is right there `core/storage/conf.py`);
-**Keys retain the dot-separated format character by character**; in the value file, `"core.storage.pack.max.byte"` represents a single attribute name and is not expanded into a nested object.

## 3. Write to disk: Each declaration is committed immediately; keys are not deleted during runtime.

| Channel | What to do | User |
|---|---|---|
| **Default** | Submit on the spot each time (by the engine) | Conventional notation |
| **Process Exit** | OnConf handles it internally once, as a fallback | No invocation required |

The engine's `sync()` / `flush()` is still present, but **the kernel side does not include it**: there are no pending commits under `flush_window=0`.
The statement indicates that the “complete submission point” has degenerated into a no-op (the original invocation of this type has been deleted).

**Runtime non-deletion rule**: The deletion criterion—“the fact exists, but the expectation does not”—holds only when the **expectation set is complete**, whereas the expectation set at runtime…
Only the portion that this process has declared. Therefore, no keys in the dictionary should be deleted; keys that are not declared in the value file should be **left as they are**.
Convergence (removing redundant keys and overwriting existing values) is performed via the command line `onconf build`/`sync`.

## 4. Write direction: code → file, unidirectional and non-overwriting

```python
conf("core.log.level", "WARNING")  # 声明；文件里没有就补上
conf("core.log.level", "DEBUG")  # 文件里已有值 ⇒ 尊重文件，只记一条 skip
```

**Modify values via the configuration file** (manual editing is the proper way to change values). During the runtime, there is **no coverage of the exit**: 2.0 has removed the one from 1.0.
It covers manual actions that are performed via the command line.

## 5. Type: No recording, no inference, no conversion

2.0 and later: The entire section has been removed; the vocabulary list now only records **key/description/default value**.

-**No inference**: The type of the value is determined by the container; the engine remains agnostic to the value—what is written in the file as `"8080"` will be read back as a string.
-**No conversion**: When using integers, write `int(conf("…"))`; the storage group of wrapper functions (such as `slot_bytes`) is precisely
It closes like this;
-**No validation**: It is a projection of key/description/default value (for IDE hover and distribution).
It is not a type constraint.

## 6. Configuring Roots and Products

```
config/
  settings.json          ← 值（使用者可改；顶部 $schema 指向词表）
  schema/settings.json   ← 词表（给 IDE 悬停与分发看的 JSON Schema）
  audit.log              ← 引擎的审计日志（运行期簿记，不入库）
  theme/…  shapes.json   ← 与配置引擎无关的**手写**声明文件，只是同住一个目录
```

-**The configuration root has a knob `CAIRN_CONFIG`**: It is only used for test and deployment redirection, and is **not a configuration item** (it is "to find the configuration").
"Measures"), it will not appear in the document. The engine’s own root knob is `ONCONF_HOME`, default `./conf`; this bin explicitly provides
, because the default landing point differs from the position inside the warehouse `config/`;
-**The command line must be explicit `--home config`**: The CLI does not know where the kernel has mounted the root filesystem; its default is `ONCONF_HOME`.
Or `./conf`. Therefore, without the time markers `--home config` `onconf build` / `sync` / `check`, a separate warehouse root will be created.
There are only those few statements generated by itself over there, which are unrelated to the inbound products under `config/` (those two commands in the access control system).
They all bring it with them);
-**Audit logs do not persist on the endpoint**: The engine’s logs have one record and two output channels—there is no toggle for the file-based output (default).
`<root>/audit.log`), the console's switch is controlled by `log_console`. The kernel is the party that is embedded by the command line and the tests.
A single import operation needs to read over a dozen keys, so the kernel **disables** the console and retains the full set of logs.
-**Write permissions are determined by the process tree**: The process that creates the engine is the owner; descendant processes have read-only access (the engine records the PID at creation time, and also considers…).
(1). **Note**: The parent process will write this variable into `os.environ`, which is spawned by Python.
The child process inherits, so it is classified as a derived process, and writing the configuration immediately triggers an exception. Let the child process become its own parent.
(It is indeed a brand-new process.) Simply uncheck this option within its environment.
-**Value file is a single copy**: The filename stem `settings` and the type `json` are both engine defaults; this repository does not modify them.

## 7. No generation script, but data is imported into the database.

Both products do not have dedicated generation scripts: they are generated automatically each time the program is run (with each declaration being submitted on the spot). Whether or not it is entered into the warehouse depends on
It uses the newly generated copy in an empty directory as the baseline for comparison before committing it to the repository.
That one—so the “declaration was changed, but the product was forgotten to be re-generated”—will get caught by it.

Reference page `docs/reference/config.md` Generated by `scripts/docgen.py`: key/default value/description reads the library word list,
**Declaration site** is determined by the AST scanner based on the call site (only literal keys are recognized; keys written inside loops are ignored).

> The dictionary format changed in version 2.0 (不再写 `type` is no longer used), but the engine **will not rewrite the dictionary just because the format is old**: writing to disk is only triggered by reconciliation.
> Action triggered (key missing, or the description/default value is inconsistent with the declaration); when neither the declaration set nor the registration entry has changed, not a single byte is written.
The old format will remain on the disk. Therefore, during that upgrade, you need to **delete the word list and generate it again** so that `to_schema` can produce new forms.
> (The `x-onconf-hash` at the top of the vocabulary list is only written in version 2.0 and does not factor into the "write or not write" decision.)

## 8. Semantic Changes (Memorize Each Version One by One)

| Item | 1.0 | 2.0 (Current) |
|---|---|---|
| **Undeclared keys** | Submission points are cleared | **Left unchanged at runtime**, convergence handled via the command line |
| **Overwrite existing values** | `force=True` Key-by-key force write | **This capability is not available**; use the command line |
| **Type** | Declaration-time validation default value | **Cancel**: do not record/do not infer/do not convert |
| **Engine Parameters** | Can be transparently passed through, including `log=` | Only goes through `AutoConf`; parameter surface is sealed; logs are split into two output channels: files and the **console** |
| **Inter-process** | `.lock` / `.key` Handshake file | **Owner process** (PID + `ONCONF_OWNER_PID`) |
| **Visibility of externally modified data** | Only enters memory with the next commit | Before reading, compare the fingerprint (size + hash); if modified, re-read |
| **Exception** | `KeyNotRegisteredError` / `KeyHasNoValueError` / `TypeConflictError` / `ConfError` | Same as left, `TypeConflictError` canceled along with type validation |
| **Duplicate declaration of the same key** | Silent pass (only updates the vocabulary) | Same as above |

> "Unknown keys are no longer cleared" is the most obvious reversal between version 2.0 and version 1.0: in version 1.0, the principle was that "the key space is determined by declarations, not by files."
2.0 Move deletion out of the runtime—under a multi-process environment, the runtime’s expected set is never complete.

## 9. Boundary

-**Declare ownership individually**: The user declares within their own package (storing parameters in `core/storage/conf.py`, while the kernel's own are in
`core/params.py`);`core/conf.py` Just assemble, without managing other packages;
-**Format constants not configurable**: Values such as the magic number, file header length, and slot header layout—changes to which would break the library—are kept within the implementation.
(`core/storage/pack.py` of `MAGIC` / `HEADER_SIZE` / `RECORD_HEAD_SIZE`);
-**Items that have already been written to disk are not overwritten by new configurations**: The grid length is written to the header of the carrier file and subsequently read from the header.
-**The engine is not part of this warehouse’s codebase**: Configuration-related logic is moved to OnConf; the kernel side is left with only two responsibilities: “configuration root” and “log output.”

## 10. Not performed/Known limitations (record as is)

-**OnConf cannot be statically typed**: The 2.0 wheel still does not include `py.typed`, so `pyproject.toml` is provided.
That group has opened. After the upstream issue is resolved, delete that section.
-**"Declaration must be a literal" has access control**: (one check in pre-commit and one in CI)
Count scan warnings as failures—any occurrence of a constant name or expression in the declaration, or any inconsistency between the two imported artifacts and the declaration, results in an immediate red flag.
-**"Duplicate declaration triggers an explosion" does not have this gatekeeping capability**: If you want it, you’ll need to implement it elsewhere (e.g., in a scan that checks call sites).
AST access control);
-Does not maintain source markers indicating whether a value originates from a declaration or has been modified; the value file remains a single copy.
