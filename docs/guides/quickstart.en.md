<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Quickstart

!!! warning "There is no usable interface yet"

    Cairn is **not released** (`0.0.1` / pre-alpha). The desktop shell (Tauri plus a web frontend,
    `app/`) exists and the sidecar and forwarder are wired, but the interface is far from complete.
    The kernel (`py_src/core/`) is usable; the domain layer (`py_src/model/note/`) has shapes and
    carriers only, and the **byte-normalisation layer for payloads has not landed**
    ([L0 storage design](../architecture/storage-design.md) §11; that page is not translated yet).

## 1. Set up

**Python 3.14** and [`uv`](https://docs.astral.sh/uv/) are required:

```powershell
git clone https://github.com/HanYang06/cairn.git
cd cairn
uv sync                 # create .venv and install every dependency (no Qt component)
```

## 2. Run the kernel

The kernel does not depend on Qt and can be used directly. The vault root is always passed in
explicitly by the caller:

```python
from core.init import Kernel
from model.note.types import NoteGroup

with Kernel.create("vault") as kernel:  # create and assemble a vault; use Kernel.open for an existing one
    group = NoteGroup()  # zero-argument construction: the block signs its own identity
    group.title = "todo"
    group.notes.extend(["n1", "n2"])

    ident = group.save()  # persist; returns the block identity
    print(ident.value_uuid, ident.in_pack_slot)  # uuid4 is the identity / the segment list is which slots it occupies

    fetched = NoteGroup.fetch(ident)  # read the same class back by identity
    print(fetched.title, fetched.notes)

    print(kernel.engine.index.tables())  # which identity tables the store holds
```

Key points:

- **Writes are issued by the block itself**: `group.save()`. The assembly point (`Kernel`) has
  **no `store` method** — placement is decided by the `Attr` / `Body` declarations on the class
  body, and a `store` on the command surface would bypass exactly that.
- **A block has two domains**: attributes go to **attribute slots** (overwritten in place), bodies
  to **body slots** (append-only, deduplicated by digest, with the digest of the current body
  recorded in the store). Both live in one location segment (**body slot first, attribute slot
  after**), and "which slot is what" is answered by the **slot-kind header** — the store no longer
  keeps a column for it: **slot numbers are only meaningful inside a pack**, so associations that
  cross a pack (or even a hub, such as referencing a body stored elsewhere) can only use a
  **digest**: the body's location is recorded in the location row of the body index.
- **The index database is the authoritative view**: `<root>/catalog.db` holds identity, location
  and body digest; `<root>/<hub>/packs/*` (carriers) **hold values only** and never a single byte of
  identity. **There is no scan-based rebuild**: lose the index and identity plus location are gone.
- **Nothing is encrypted locally**; data is stored in the clear. Encryption applies to transport
  and remote replicas only, and is not implemented yet.
- **Known gap**: putting a `NoteLine` object into `NoteData.lines` **cannot be persisted** —
  `cbor2` cannot encode a dataclass, and the byte-normalisation layer for domain payloads
  (`py_src/model/note/format/`) is not implemented. What round-trips today is scalar attributes and
  plain JSON values (such as `NoteTag.entries` with its `dict[str, list[str]]`).

## 3. Run the tests

The tests need no external service and always use a temporary local vault:

```powershell
uv run pytest                                        # everything (with coverage)
uv run pytest tests/core/test_engine.py -x           # one file
uv run pytest -k "conf" -x                           # filter by name
```

## 4. Run the desktop shell (experimental)

```powershell
pnpm --dir app tauri dev
```

- Requires a Rust toolchain plus Node and pnpm.
- The shell reaches the kernel through the sidecar: it starts a Python process with
  `python -m app.sidecar <vault root>`. The interpreter and module path come from
  `CAIRN_PYTHON` / `CAIRN_PYTHONPATH`, and the vault root from `CAIRN_VAULT`
  (falling back to `vault/` under the working directory).
- Incomplete: the command surface and the notification direction are connected; the interface
  itself is still being built.

## 5. Next

- To change code → [Development](development.md) and [Conventions and red lines](conventions.md)
- To read the design → [Architecture index](../architecture/index.md); for L0 storage the
  authority is [L0 storage design](../architecture/storage-design.md)
- To look up the exact signature of a class or function → [API reference](../api/index.md)
