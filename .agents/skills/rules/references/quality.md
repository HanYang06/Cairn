<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 质量标准（企业级-ε）

本仓库的质量口径：严格度在「草台班子」与「金融级」之间，约等于**企业级再降半档**。
`pyproject.toml` 是配置的**唯一事实来源**；本文件只写口径、豁免理由与升级路径。

## 五个方面

### 1. 注释：有要求

- 公共**模块 / 类 / 函数**必须有 docstring（pydocstyle，google 约定）。
- 不强制每个方法 / 魔法方法 / `__init__`（豁免 `D102` / `D105` / `D107`）。
- 中文 docstring 以「。」结尾，`D415` 不认全角句号 → 豁免 `D415`。
- 测试、工具脚本整体豁免 `D` 系（`tests/` `tools/`）。

### 2. 代码风格：有规范

- `ruff check`：`select = ["ALL"]`，再用一份**逐条写明理由**的 `ignore` 收口。
- `ruff format` 强制：提交前与 CI 都检查（`ruff format --check`）。
- 复杂度 / 裸 `except` / magic value / 导入分层等默认开启。
- vendored 第三方技能（`.agents/`）排除，保持上游原样。

### 3. 类型：按静态语言口径

- `mypy strict = true`，覆盖 `py_src`、`tools`、`scripts` 与 `tests`
  （门禁命令 `uv run mypy py_src tools scripts tests`）。
- `mypy_path = "py_src"` 指明源码根：不指路时 mypy 把 `core` 当成缺 `py.typed` 的已装包，
  测试侧的 `core.*` 全成 `Any`，报错数仍在、判据已失效。
- 未注解、隐式 `Any`、`Any` 返回值、缺泛型参数一律报错。
- **测试只豁免签名**（`tests.*` 关 `disallow_untyped_defs` / `disallow_incomplete_defs`）：
  函数体仍在 `check_untyped_defs` 下受检，对 `core.*` 的调用判据一条不少；
  口径与 ruff 对 `tests/**` 豁免 `ANN` 一致。
- **类体上写 `字段: T = 声明(...)` 时，声明与类型对不上，用 `type: ignore[assignment]`
  并配一句注释**（描述符在实例上交出 `T`，而右值是声明对象）。这是已知的取舍，
  不是"用 ignore 掩盖错误"——掩盖的是 mypy 对描述符的静态推断，不是真实缺陷。
- 例外：`id` / `type` / `hash` 是本项目的**领域词汇**，豁免 `A002` / `A003`。

### 4. 魔法：少用、不滥用

**魔法不是不用，而是少用、不滥用。** 能用正常 Python 写法解决的，就不要用魔法——
因为魔法的**可解释性与可测试性都更弱**：多数 Python 开发者读不懂它，少数高级开发者也只
熟其中一部分。读不懂的代码，出问题时只能靠猜，而"猜"是不能写进门禁的。

判据是**下一句能不能用大白话讲清楚**。讲不清就是魔法。

三档，按此优先：

| 档 | 是什么 | 规矩 |
|---|---|---|
| **正常写法** | `__init__` 里赋值、普通方法、普通继承、`@property`、`@dataclass` | **首选**。能这么写就这么写 |
| **可解释的语法** | `__init_subclass__`、类体上的描述符、`__slots__`、`@classmethod` | **允许，但要在注释里写清"为什么不能用正常写法"** |
| **冷门魔法** | 元类、动态改类属性、`__getattr__` 兜底一切、运行期生成类型、改写 `__mro__`、猴子补丁改库行为 | **默认不用**。要用须在代码里写明理由，并在评审时被问过一次 |

三条落地要求：

1. **机制要看得见**：一件事的来路写在**同一条链**上。反例：块的身份来自引擎内部的
   `ID.unbound()`——读块类的人看不到"身份从哪来"。正例：身份由块自己那两行给出
   （`self.id = ID(self)` + `super().__init__(self.id)`，或由调用方递进来）。
2. **不用运行期猜来补信息**：拿不到就写清楚拿不到，不要用 `getattr` 兜底、不要扫
   `vars()` 去猜"这大概是什么"。**判据落在值上**是可以的（那是数据），
   但"靠猜结构"不行。
3. **冷门写法要配用例**：一处魔法至少一条直说它行为的用例。没有用例的魔法，下一轮改动
   就会悄悄坏掉，而且**不报错**。

**测试也是给人读的**：用例用正常写法，别用魔法去省几行——用例是规格的说明书。

**门禁**：`uv run python scripts/magic.py --check`（pre-commit 与 CI 都跑）。两道闸：

- **豁免表**（`scripts/magic.py` 的 `ALLOWED`）：类上的 dunder 逐个比对，表里没有的一律失败。
  要加一个，就在表里加一行并写明理由——**那一步就是评审点**；
- **比例上限**（`MAX_RATIO`）：用到魔法的类占全部类的比例。当前实测 0.20、上限 0.30，
  它的作用是**防涨**。真要砍就砍下去再把这个数改小——**门禁数字只许往下走**；
- `__init__` 不算魔法（正常写法，几乎每个类都有）；`--report` 只看现状、不判失败。

### 4.1 类变量：也少用

**类变量（`ClassVar`）少用。** 它与类属性性质相近，但**用起来不够顺**：读的时候要分清
"这是类上的还是实例上的"，改的时候更要小心（改了类上那一份，所有实例一起变）。
清晰是清晰，可每次用都得先想一遍，不划算。

只在**两处**用它，且都要能一句话说出理由：

1. **它真的是"整个类型共享的一件事"**——如 `Block.max_bytes`（体积上限）、
   索引类的 `manages`（管哪一类字段）。这类值整个类型只有一个，实例上带一份是多余的；
2. **它必须由运行期读取，而不是给人读**——如引擎按 `max_bytes` 决定续不续块。

反例（本仓踩过的那一个）：把"这个字段的落点"塞进**实例**值里（`self.title = Attr("")`），
结果赋值一步就把声明覆盖了，字段的静态类型与声明还互相打架。
**那种信息属于类体，不属于实例。**

### 5. 其他：按企业级

- **测试**：`pytest --strict-markers --strict-config`；`filterwarnings = ["error"]`（warning 零容忍）。
- **覆盖率**：行 + 分支 ≥ 80%（CI 门禁 `--cov-fail-under=80`）。
- **提交前**（`.pre-commit-config.yaml`，共 13 个钩子；**须先 `uv run pre-commit install`**，
  否则一个都不跑）：
  SPDX → 书面语 → 标点（报告模式）→ 魔法用量 → `onconf check --strict`（配置声明）→
  `ruff check --fix` → `ruff format` → `deptry` →
  `lint-imports` → `mypy` → `uv lock --check` → `pytest` → 前端 `pnpm check`。
  **提交信息不再由本地钩子校验**（2026-10-10 撤掉 `commit-msg` 钩子与 `scripts/commitmsg.py`）：
  Conventional Commits 仍是成文约定，但写偏不会被拦下。
- **CI**（`.github/workflows/ci.yml`，Python 侧十四步 + 前端一组 `pnpm check`）：
  SPDX → 书面语 → 标点 → 魔法用量 → 配置声明 → 文档防漂移 → docstring 覆盖（报告）→ ruff → deptry →
  import-linter → `uv lock --check` → mypy → pytest + 覆盖率门禁。
  **输出编码统一 UTF-8**（workflow 级 `PYTHONIOENCODING: utf-8`）：Windows runner 的 stdout
  默认不是 UTF-8，而 `lint-imports` 的报告里含中文契约名，打印即 `UnicodeEncodeError`。
  实测复现：`PYTHONIOENCODING=cp1252 uv run lint-imports`。
- **架构校验**（`uv run lint-imports`）：契约写在 `pyproject.toml` 的 `[tool.importlinter]`——
  `core` 不许依赖上层（`model` / `feature` / `app` / `net` / `server`）且必须 Qt-free。
  配置放 pyproject 而非 `.importlinter`：后者按系统默认编码读，Windows 下遇中文即失败。
- **依赖盘点**（`uv run deptry .`）：拦"声明了却一处没用"与"用了却没声明"；
  已知的未接线依赖冻结在 `[tool.deptry.per_rule_ignores]`，故新增的才会红。
- **标点**（`uv run python scripts/punct.py`）：**注释与 docstring** 用半角标点（中英混排），
  字符串字面量不动（那是行为不是排版）。当前是**报告模式**：全仓命中约 5300 处，
  看过一轮再改成阻断式。

## 全局豁免清单（每条都有理由）

见 `pyproject.toml` 的 `[tool.ruff.lint] ignore` 内注释，摘要：

| 规则 | 理由 |
|---|---|
| `D203` `D213` `COM812` `ISC001` | 与 `ruff format` 冲突，交给格式化器 |
| `RUF001` `RUF002` `RUF003` | 中文全角标点误报 |
| `D415` | 中文 docstring 以「。」结尾，规则不认 |
| `D102` `D105` `D107` | 不强制方法 / dunder docstring |
| `ANN401` | 边界处允许显式 `Any`（未注解由 mypy 把关） |
| `TID252` | 项目内部允许相对导入 |
| `EM101` `EM102` `TRY003` | 异常消息允许字面量 / f-string |
| `PLR2004` | 可读性阈值判断不算魔法数 |
| `A002` `A003` | 领域词汇 `id` / `type` / `hash` |

按文件豁免（`per-file-ignores`，以 `pyproject.toml` 为准）：
`py_src/core/storage/db/engine.py` 的 `S608`（表名与列名由 `ID_FIELDS` 现算并经 `_quote` 加引号，
值全部参数化）、
`py_src/model/**` 的 `FBT003`（`Attr(False)` 里那个布尔是**声明的默认值**，
不是"给函数加开关的布尔位置参数"），以及测试 / 工具脚本的整组豁免。

另有一处**反向**的取舍值得记：`[tool.ruff.lint.flake8-type-checking]` 那一节**已删**。
旧范式下块类型的 `__init__` 体要在构造时跑声明表达式，故必须声明 `runtime-evaluated-base-classes`；
现值范式把声明写回类体，而注解一个都不求值（`Attr` / `Body` 只认字段名，不读注解），
留着它会把"只给 mypy 看的领域类型"误判成运行期要用。

## 安全扫描（与质量门禁同等地位）

威胁模型与报告渠道见 [`SECURITY.md`](../../../../SECURITY.md)；此处只记**怎么接线、为什么这么接**。

| 检查 | 何时跑 | 拦什么 | 阻断？ |
|---|---|---|---|
| **CodeQL**（`codeql.yml`） | push/PR 到 main · 每周一 | **跨文件污点传播**（Python / JS-TS） | ✅ |
| **dependency-review**（`ci.yml`） | **每个 PR** | 本次改动**新增**的有漏洞依赖 | ✅（moderate 起） |
| **pip-audit**（`ci.yml`） | push 到 main · 手动 | Python 依赖的已知 CVE | ✅（实测零命中） |
| **pnpm audit**（`ci.yml`） | push 到 main · 手动 | 前端依赖的已知 CVE | ✅（命中即处理：能顶版本就顶，**无补丁的按单条 GHSA 豁免**并写明到期条件） |
| **gitleaks**（`ci.yml`） | push 到 main · 手动 | 提交历史里的密钥 / 令牌 | ✅ |
| **ruff `S` 族**（`ci.yml`） | 每个 PR | 单文件里的危险写法 | ✅ |

**为什么要分"PR 跑"与"主分支跑"**：PR 上只判**新增**风险（dependency-review），
主分支上跑**全量**（audit / gitleaks）。反过来会让一堆历史遗留问题把无关的 PR 卡死，
而门禁一旦常年红，人就会开始绕它——那比没有门禁更糟。

**五条实现要点（都是踩过的）**：

- **`pnpm audit` 必须显式指官方 registry**：本仓 npm 源配的是 `registry.npmmirror.com`，
  它没实现 audit 端点，裸跑直接报 `ERR_PNPM_AUDIT_ENDPOINT_NOT_EXISTS`。
- **pnpm 10 起不再读 `package.json` 的 `pnpm` 字段**：想加 `overrides` 得写
  `app/pnpm-workspace.yaml`（实测 pnpm 12.8.1：写在 `package.json` 里只回一条
  `[WARN] ... no longer read by pnpm ... ignored: "pnpm.overrides"`，然后**什么都不做**）。
- **无补丁的漏洞按单条 GHSA 豁免，不用 `--ignore-unfixable`**：后者把"所有没有补丁的漏洞"
  一次性闭眼放过，将来真出现必须处理的也不会有人发现。当前那一条（`braces`）的理由与
  到期条件写在 `ci.yml` 的审计步骤旁，裁定记在记忆 `仓库治理.md`。
- **`pip-audit` 断言的是"已装环境"**：本仓 `pip-audit` 报 `cairn ... not found on PyPI` 是
  **正常**的（自身未发布 PyPI），不是失败；它扫的是依赖树。
- **要按 CI 的路径验，别只看本机**：本机 `.venv` 往往是旧的，会漏掉"锁文件里已经有的 CVE"。
  实测一次：本地报零漏洞，CI 上全新 `uv sync` 报出 `virtualenv 21.7.10` 的四个已知漏洞
  （PYSEC-2026-4011/4012/4013/4014）。**传递依赖的下限也要盯**——已把 `virtualenv>=21.7.13`
  写进 dev 依赖把洞顶掉（写显式下限比等上游放开可靠，因为它是 CI 真会拦的那条线）。

**不引 `bandit`**：ruff 的 `S` 规则族（`select = ["ALL"]` 已含）覆盖同一批检查，
再引一个只是多一套配置与一份噪音。

**`pull_request_target` 是本仓的一条红线**：它能在 fork PR 上拿到 secret，
而"不执行 PR 代码"这条保证**只在 composite action 内部成立**——一旦那个 action 变了、
或有人在工作流里加一句 `checkout` PR 分支，密钥即泄露。
故**用它的工作流一律不放进 `.github/workflows/*.yml`**。曾按此做过两件事：`ocr-review` 先改名
`.on-run` 停用、后又改回 `.yml`，直到 2026-10-10 **整个工作流删除**（作者口径：个人资产有限，
玩不起按调用次数计的 LLM 额度）。要用 AI 评审须先写清"为什么不执行 PR 代码"，并接受额度成本。

**仓库设置里还应打开（不在文件里，故记此处）**：

1. **Secret scanning + Push protection**（公开仓库免费）：与 gitleaks 的区别是**推送时**就挡。
2. **Dependabot alerts / security updates**：`dependabot.yml` 管的是**版本更新**，
   这两项管的是**漏洞告警**，互不替代。

## 升级到「全企业级」

- 打开 `D103`（公共函数）与 `D102`（方法）的 docstring 要求。
- 覆盖率阈值提到 90%+。
- **依赖审计已是门禁**（上表）；若要再加一层，候选是 `osv-scanner`（跨生态、可扫锁文件本身）
  与 `actionlint`（工作流 YAML 的语法与语义检查；`zizmor` 更偏安全审计，两者不冲突）。
