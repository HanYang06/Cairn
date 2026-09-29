<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 进度 / TODO

> 状态：进行中 / 已定 / 已废弃。完成后移入 `changes.md`，或直接删除。
> 细则以 `docs/architecture/*.md` 与代码为准，本文件只记「还没做 + 在做」。

## 内核重建（2026-09-29 立项；**当前唯一主线**）

> 分支 `refactor/clean-local-code`：旧实现整条删除（137 文件 / 21045 行），本文其余内核条目均为存档。
> 作者口径：代码优先、以新代码方向为准、随片带最小回归测试、文档与仓库尾巴后补；
> 内核只管事件 / 存储 / 配置 / 异常四件事，总量应当很小。方向见 `decisions.md`「内核重建」。

- [x] **片 1 · 身份与块底座**（2026-09-29）：`core/exc.py`（`CairnError` / `InvalidIdError`）、
  `core/storage/format/id.py`（`ID` 两套凭证 + 位置段；修掉共享默认值硬伤）、
  `core/storage/format/block.py`（`Body[T]` / `Block[T]`，PEP 695）、`tests/core/` 13 例。
  ruff / format / mypy strict / pytest / SPDX / 书面语全绿。
- [x] **片 2a · 事件对象与总线**（2026-09-29）：`event/events.py` 的 `Event`（冻结；字段名借 CloudEvents
  口径 `id` / `source` / `type` / `time` / `subject` / `data`，明写不代表实现该规范）、
  `event/bus.py` 的 `Bus` 与 `Subscription`（按注册顺序投递、异常隔离并交回失败清单、显式撤订、
  失败钩子）；`tests/core/test_events.py` 5 例 ＋ `test_bus.py` 13 例。六道门禁全绿，覆盖 96%。
  **分发自制、不引库**（blinker 实测三条不合需求，装上后已撤净）：理由见 `decisions.md`「事件引擎自制」。
- [x] **片 2b · 事件层收口**（2026-09-29，作者交办代定）：事件引擎到此完整——`Event` + `Bus` +
  `Subscription`，只做扇出通知。`event/parser.py` 的 `EventParser` 空桩已删（全仓无引用）；
  **决策层（形式二的中介者）明确不做**，重启条件见 `decisions.md`。删后门禁全绿：30 例、覆盖 96%。
- [x] **片 3 · 存储格式与载体**（2026-09-29）：`storage/format/record.py`（记录头＋ID 段＋载荷，
  编码/解码与逐项自校验）、`storage/carrier.py`（24 字节文件头、**两数格模型**的追加写与按格区间读、
  顺扫）、`storage/format/id.py` 补落盘子集；`core/exc.py` 补 `StorageError` /
  `RecordFormatError` / `SlotError`。测试 39 例；六道门禁全绿（79 例、覆盖率 99%）。
- [ ] **待回写 · 设计篇 §5.2 / §5.6 / 词汇表**：定位模型已由作者推翻为两数格模型（槽长推荐值
  64 KiB → 512 B）；术语"桶 / bucket"改为"hub"。`storage-design.md`、`AGENTS.md` 与 `data-model.md`
  里的旧口径待文档那一轮一并改正（记忆已记全口径）。
- [x] **片 4 · hub 层**（2026-09-29）：`storage/hub.py` 落实际逻辑——形状判据（`vault/<hub>/packs/`）、
  **读路径不建 hub**（目录不在即报错，建立是显式动作）、**活跃载体＝有空间的最满者**（同大小按名字定序，
  判据完全确定；一个都没有就新开随机名载体）、`append` / `read` / `scan`；策略参数（槽长、封口线）
  由上层传入，hub 不落盘自己的配置；新载体取当前策略槽长，既有载体一律以文件头为准。
  `core/exc.py` 补 `HubNotFoundError` / `HubShapeError`。测试 `test_hub.py` 18 例；
  六道门禁全绿（97 例、覆盖率 99%）。
- [x] **片 5a · 表声明层**（2026-09-29）：`storage/tables.py`（中立类型、重建档、约束开关、严格解析口、
  DDL 编译、索引名与跨表撞名校验、`signature()`、`KERNEL_TABLES` 三表）；`core/exc.py` 补
  `TableDeclarationError`。测试 40 例；六道门禁全绿（137 例、覆盖率 99%）。
- [x] **片 5b · 索引库开库对齐**（2026-09-29）：`storage/index.py`——开 `catalog.db`、库内 `meta` 存声明
  签名并在开库时比对（漂移只报告并更新登记）、差异分类处置（缺表即建 / 缺列即补 / 索引不符即建或拆重建 /
  多出的只告警 / 容器级漂移须 `RebuildPlan` 授权 / 重建改名隔离不删）、结构化 `Difference` 与
  `Alignment` 报告。`core/exc.py` 补 `IndexNotFoundError` / `IndexSchemaError`。测试 21 例；
  六道门禁全绿（159 例、覆盖率 99%）。
- [x] **片 5c · 行层与档一重建**（2026-09-29）：`storage/rows.py`——定位行 / hub 登记 / 关系边的读写，
  以及"以载体为真源、只补缺行"的档一重建（已有行不动、坏点即停、重跑幂等）。
  测试 16 例；六道门禁全绿（174 例、覆盖率 99%）。
- [x] **片 6 · 存储引擎**（2026-09-29）：`format/block.py` 的载荷面（保留键 ＋ 指针编解码）、
  `storage/engine.py` 的 `Storage`（store 落两条记录并按内容去重、load 按身份读回、body 按地址读回、
  drop 只摘块行、locate 诊断）、`core/event/catalog.py` 的事件目录、`core/clock.py` 收口时钟。
  测试 16 例；六道门禁全绿（189 例、覆盖率 99%）。
- [x] **片 7 · 巡检与处置**（2026-09-29）：`storage/patrol.py`——六类发现、双向比对、坏点不即停、
  处置只补不删（补登记 / 补行 / 只改坐标）；配套 `hub.find_hubs`、`Hub.carrier` 公开、
  `Rows.locations` 与 `Rows.move_location`；引擎建 hub 时一并登记。测试 12 例；
  六道门禁全绿（201 例、覆盖率 99%）。
- [x] **片 8 · Kernel 接线**（2026-09-29）：`core/init.py` 的 `Kernel`（库根 ＋ 事件/存储两个引擎的装配、
  路径约定只此一处、失败→日志联动、`patrol`/`repair` 维护入口、`store`/`load`/`drop`/`locate` 短面）。
  配置引擎与对象管理表按口径**不在本层**（前者作者自办、后者是预留）。测试 13 例；
  六道门禁全绿（213 例、覆盖率 99%）。**内核代码侧到此收口**：事件 / 存储 / 异常三个引擎 +
  Kernel 装配都在，且 `Kernel.create → store/load → patrol/repair` 端到端跑得通。
- [ ] **待作者裁定 · 摘块与巡检的相互作用**：`drop` 只摘行、记录留在载体里（追加写不动旧字节），
  于是巡检把块记录报成 `missing_row`、处置又把它补回来（等于撤销摘块）。消掉它要么引入墓碑
  （`drop` 写一条"已删"记录，巡检据此不补），要么等压实回收落地——两条都属未来项。
- [x] **片 9 · 仓库尾巴**（2026-09-29）：`pyproject.toml`（hatch packages / isort first-party /
  失效的 per-file-ignores / `--cov=feature` / 退役工具的 mypy 豁免）、文档站（nav 去掉已删的评审记录、
  三页 API 改成"待重建"占位、`core.md` 按真实模块重写、`api/index.md` 改现状）、`ci.yml`（暂时摘掉
  配置投影那一步）、`build-windows.yml`（去掉标签触发）、三个退役工具的 docstring。
  **本地跑通 CI 全套门禁**：SPDX / 书面语 / docgen ×2 / ruff ×2 / mypy src tools /
  pytest --cov-fail-under=80（213 例、99.54%）/ mkdocs --strict —— 全绿。
- [ ] **待作者裁定 · 依赖盘点**：`blake3` / `argon2-cffi` / `cryptography` / `fastcdc` / `pyyaml` /
  `tomli-w` 在 `src/` 与 `tools/` 里**一处引用都没有**（详见 `changes.md` 片 9 末段）。
  裁掉能缩短安装与供应链面；留着的理由是各自的上层（分片、配置引擎、传输加密）还要回来。
- [x] **片 10 · 文档回写**（2026-09-29）：L0 唯一事实来源 `storage-design.md` 通篇按实现重写
  （hub 术语、两数格模型、512 B 格长、三表加 `meta`、`DERIVED`/`SOURCE`、开库比对语义、六类发现）；
  `AGENTS.md` / `docs/architecture/index.md`（加"与代码的对应"列）/ `kernel.md` / `glossary.md` /
  `data-model.md` / 首页与两篇 guides 按现状改；作废主轴（`kernel-spec.md` / `kernel-m1-plan.md`）
  加"仅存档"横幅。验证：书面语 / SPDX / `mkdocs --strict` / pytest（213 例）全绿。
- [ ] **未来项**：压实回收（删内容要判引用）、跨行事务与崩溃恢复、批量写入合并通知、大正文分片、
  检索、`src/core/conf/`（作者自行推进），以及**领域 / 界面 / 应用三层与打包的重建**。
- [ ] **文档后续（不阻塞，逐层回来时做）**：`domains.md` / `config.md` / `note-model.md` /
  `access.md` / `ui-kernel.md` / `ui-theme.md` / `network.md` / `ecosystem.md` /
  `reference/config.md` 描述的是**尚未重建的层**，现在只在 `architecture/index.md` 里标了"意图"；
  各层重建时把对应页按实现回写（`data-model.md` 的 §2 / §3 字段表同理）。

## 存储重设计（2026-09-28 立项；**已收口**，只余未来项）

> ⚠️ 2026-09-29：本条所述实现已随 `refactor/clean-local-code` 整条删除，仅存档；当前主线见「内核重建」。

> 2026-09-30 补记（**当前口径**）：声明层已按"ID 面 + 三类表"重做（见 `changes.md` 同日那条、
> 设计篇 §8.1.1–§8.1.4）：列的来源分五种、绑定列的列名即 ID 字段名、`record` 主键
> 改成 `(name, value_uuid)`、绑定列默认建索引。**待接回的只剩**：把 `KERNEL_TABLES`
> 挪进 `config/tables.yaml`（经 `storage.db.tables` 的文件引用），届时 `core/storage/tables.py`
> 的三表常量改成读它——接法已定，不必再议形状。

> 设计篇 = `docs/architecture/storage-design.md`（**L0 唯一事实来源**，已落地，v1.3）。
> 方向见 `decisions.md`「存储重设计」。分支 `feat/storage-redesign`（已并回 `main`）。
> 旧层（旧 `Bucket` / `Catalog` / `Oid` / `Cid`）与旧篇 `storage.md` **已删除**。

- [x] **片 0 · 设计篇**：`storage-design.md`（12 节）＋ `mkdocs.yml` 登记 ＋ 逐轮裁定
  （四层 / ID 两形态 / 记录自描述 / 单库多桶 / 表声明配置化 / 可重建分档）。
- [x] **片 1 · 身份层**：`core/types/id.py`（`Id` / `ValueUuid` / `ValueHash` / `SlotRange` / `Id.record`
  与 `Id.from_record`）＋ 存储侧异常 ＋ `tests/core/test_id.py`（35 例）。
  一并：`types/ids.py` 里被取代的 `ID` 草稿删除（`Oid` / `Cid` 已于片 5c 随旧层退役）。
- [x] **片 2 · 载体与记录层**：`core/storage/carrier.py`（槽布局与载体文件头）、
  `record.py`（记录头四项 + 编解码）、`io.py`（`CarrierFile`：追加写 / 按槽区间读 / 顺扫重建）
  ＋ `tests/core/test_carrier.py`（48 例，含篡改、截断、同槽记录错位）。
- [x] **片 2b · 参数接配置**：`storage.pack.slot_bytes` 新声明（默认 64 KiB）；
  `pack.max_bytes` 收窄为**只管封口线**（默认 2 GiB）；**删** `pack.max_blocks` 与
  `version.retention_days`；两份投影与配置参考页重生成；建载体时读一次配置、此后按文件头读。
  **规矩**：格式常量（魔数 / 头长 / 记录头布局）不进配置。
- [x] **片 3 · 索引库**：`core/storage/tables.py`（表声明：中立类型 / 约束 / 索引 / 重建档，
  自校验 + 编译成 DDL）与 `core/storage/index.py`（实际结构比对 → 分类 → 处置；
  破坏性动作默认拒绝、须显式授权；入口四件事与幂等边）；
  声明投影落在配置键 `storage.tables.declared`，库内 `meta` 存一份并在开库时比对；
  `tests/core/test_index.py` 32 例。
- [x] **片 4 · 桶与多桶**（2026-09-28）：`core/storage/vault.py` —— `Bucket`（目录 + `packs/`；
  追加 / 按槽区间读 / 顺扫；活跃载体＝有空间的最满者）与 `Vault`（唯一索引库 + 多桶路由 +
  桶登记与对账）；`io.CarrierFile.scan` 改为交出 `(槽区间, 记录)`；`Index.open` 拒绝接管别人的 SQLite 文件；
  `tests/core/test_bucket.py` 27 例。**未做**：合并与短命桶（归属改写待裁定，见设计篇 §7）、巡检。
- [x] **片 4b · 巡检与处置**（2026-09-28）：`Vault.patrol()`（只报告）与 `Vault.repair()`（只处置
  可修复项），发现分六类（缺行 / 坐标不符 / 缺登记 → 可修；内容没了 / 桶没了 / 载体坏 → 只报告）；
  合并进原来的 `reconcile()` 与 `rebuild_records()`（三个入口做同一件事是"半截机制"）。
  一并与设计篇 §8.7 对齐：坏点即停属于重建，巡检按载体捕捉后继续扫。
- [ ] **未来项 · 合并与短命桶**（作者 2026-09-28 定：无所谓，记下即可，短期不做）：
  并发承接 + 合并回主桶 + 销毁；届时一并裁定"合并期桶归属改写"（改写为目标桶 / 保留源桶）。
- [ ] **片 5 · 收口**：`Oid` / `Cid` 与旧 `catalog.py` / `bucket.py` 旧逻辑退役、
  旧篇 `storage.md` 与 `data-model.md` 存储态章节清理、全量测试与记忆整理。
  **卡口**：旧层退役要先把 `Block` / `Oid` 换成 ID + body（`Storage.store(obj: Block)` 那条链），
  即 ID 专项——不是单靠存储侧能做完的一步。
- [x] **片 5a · 块面**（2026-09-28）：`core/storage/blocks.py` 的 `BlockStore` —— 块 ⇄ 记录
  （内容记录 ＋ 块记录；内容面去重；`body_addr` 指针在载荷里；`drop` 只摘行）。
  一并修正设计篇 §3.2.1：指针不在 ID 里（记录层自校验优先），故 §3.2.1 / §4.4 已回写。
- [x] **片 5b · 内核接线**（2026-09-28）：`Storage` 重写为 `BlockStore` + `Vault` 之上的适配层，
  内核只有一条存储路径；库级入口 `.catalog` → `.vault`；中立视图改由块构造；
  删 `create` 与 `mount` / `bind_tables`（后者全库无一处覆写）。接线撞出并修掉三处：
  `iter_blocks` 顺扫把**同一身份的旧副本**读成第二个对象（改为按索引走）、
  `Block.decode` 不收 `author` / `config`（读回时补）、`Vault.open` 把**告警**当开库失败
  （库里一旦建过领域表就打不开）。加护栏：旧格式的库**显式拒开**。
  `Core.mount` 换下旧挂件时一并 `close()`（否则连接要等垃圾回收才报资源警告）。
- [x] **片 5c · 旧层退役与文档收口**（2026-09-28）：删 `bucket.py` / `catalog.py` / `ids.py`
  与两个无人抛的异常；领域侧 `Oid` 机械替换为 `ValueUuid` / `str`（15 个文件）；
  测试按契约迁移（`test_vault.py` 11 条原样保留，`test_store.py` 重写为块语义契约）；
  `storage.md` 删除、全站 13 处入链改指设计篇、`data-model.md` 与术语表按新口径回写。
- [ ] **未来项 · 合并与短命桶**（作者 2026-09-28 定：无所谓，记下即可，短期不做）：
  并发承接 + 合并回主桶 + 销毁；届时一并裁定"合并期桶归属改写"（改写为目标桶 / 保留源桶）。
- 遗留 · **两处字段问题待作者裁**（设计篇 §12）：`body_addr` 提升成索引列？属性投影进库？
- 遗留 · **能力空缺**（随旧层退役，前三项原为预留、末项全库无人用）：事务与回滚、
  大正文分片、每桶一份配置、块 `config` 的"独占载体"语义、目录版本号。
- 遗留 · 写路径无事务：先落字节、后记目录；块面写两条记录（内容 ＋ 块）同理——
  中途失败可能留下没人指向的内容记录，属孤儿（由巡检补行收编，或将来清）。
- 遗留 · 更新留下的**旧副本**没有回收（同一身份盘上多份），属压实与空洞回收（设计篇 §12）。
- 已解决 · ~~`gen_conf.py` 重复跑会留下曾声明、后已删除的键~~：2026-09-30 配置引擎重做后，
  该工具**已删除**；新引擎用一份"谁登记过"的账区分用户键与过期键——用户自己加的键留着，
  曾声明后删除的键随下一轮落盘消失（见 `changes.md` 2026-09-30）。

## 书面语（2026-09-26 立项；全仓已清零，门禁已阻断）

> 方向见 `decisions.md`「书面语（2026-09-26 定 + 全仓已落，门禁已阻断）」。
> 标准本体 = `tools/prose.py` 的 `_LEXICON`；规则 `rules/references/prose.md`；门禁在 pre-commit + CI。

- [x] **片 1 · 工具与标准**：`tools/prose.py` + `rules/references/prose.md` + 路由表 +
  `AGENTS.md` 命令 + pre-commit 钩子 + CI 步骤 + `tests/tools/test_prose.py`。
- [x] **片 2 · 全仓清洗**：118 处命中 → 0 处；含架构文档 13 篇、规则与记忆、
  `src/core` / `src/feature` / `src/ui_tools` / `tests` 的 docstring、向导与术语页、README。
- [x] **片 3 · 误报治理与转阻断**：词典加行首例外 `Term.not_at_line_start`（三叹号 admonition
  不再误报），余下命中清零后，`ci.yml` 与 pre-commit 的书面语步同步转为**阻断式**。
- [ ] **片 4 · 词典扩容（持续）**：目前只收**歧义为零**的标记；后续发现新口语词时追加进
  `_LEXICON`（并在 `changes.md` 记一句）。**已在代码审查中发现的候选**：泛用动词「搞」系
  （需精确正则）、非正式省略的收尾语气——均需先确认歧义再收。
- [ ] **片 5 · 英文文档**：现无英文文档，词典亦无英文条目；将来加 `docs/en/` 时需补英文口语规则
  （第二人称、缩写等）。

## 文档体系（2026-09-26 立项；第一片已落，见 `changes.md`）

> 方向见 `decisions.md`「文档（2026-09-26 定 + 已落）」：手写事实源 + 自动生成两条线，不许合并。

- [x] **片 1 · 骨架**：`mkdocs.yml`（Material + mkdocstrings，strict）+ `docs/index.md` +
  `docs/architecture/index.md`（逐篇状态 + 权威顺序）+ `docs/guides/` + `docs/contributing/` +
  `docs/reference/glossary.md` + `docs/api/`（四层包自动抽取）+ `.github/workflows/docs.yml`
  + `rules/references/docs.md` + README 重写为稳定门面。
- [x] **片 2 · 生成补真**：`tools/docgen.py` —— 配置参考页 `docs/reference/config.md`
  **整页生成**（入库，`--check` 防漂移进 CI；2026-09-30 起取材改为**从声明现算**，
  不再读入库的副本，见 `changes.md` 那条）；
  `--coverage` 出 docstring 覆盖报告。**规则：能算的就不写、能查的就不写。**
- [ ] **片 3 · docstring 覆盖补齐（有缺口，勿忘）**：公共类 / 函数 **579 个、117 个没 docstring
  （79.8%）**，因 `show_if_no_docstring: false` 而**从 API 页静默消失**。
  缺口最大：`feature/shared/canvas.py` 13、`feature/note/tools.py` 12（`core/storage/catalog.py`
  已随旧层退役删除）。补到 ≥95% 后把 `tools/docgen.py` 的 `DOCSTRING_MIN` 接成
  `--coverage --strict` 门禁。
- [x] **片 4 · 存储篇回写**（2026-09-28）：存储这摞文档已按新底座回写并收口——
  `storage-design.md` 升为唯一事实来源、旧篇 `storage.md` 删除、`data-model.md` 的存储态
  与术语表不再写"目录唯一真源"。其余各篇仍随实现逐步回写。
- [ ] **片 5 · 中文搜索**：`jieba` 分词未引（本机构 sdist 失败）；需要时补，属构建期依赖。
- [ ] **片 6 · 发布接线（人工一次性）**：仓库 Settings → Pages → Source 选 **GitHub Actions**；
  之后 `main` 的文档变更自动发布到 <https://hanyang06.github.io/cairn/>。自定义域名暂不需要。
- [ ] **可选**：多语言（zh/en）站点；依赖图 / 类型表等更多"从代码投影"的页面（`docgen.py` 已有落点）。

## 配置引擎（2026-09-29 重定；**2026-09-30 已落地**，只余未来项）

> 形状见 `decisions.md`「配置（2026-09-29 重定 + 已定形）」，用法契约是 `docs/architecture/config.md`
> （**现行**），落地记录见 `changes.md` 2026-09-30 那条。**不再有 `scope`**：
> 事务由引擎自己组织（写只记一笔、退出统一落盘）。

- [x] **引擎**：`core/conf/` 的 `conf` 面（声明 = 取值）、待写批与批内可见、单向写入 + `force`、
  `sync()`、类型判据（`type(v) is T`、`bool` 不冒充 `int`、`int`→`float` 提升、JSON 值域）、
  `file=` 引用、`atexit` 落盘、`CAIRN_CONFIG` 旋钮。
- [x] **投影**：`config/settings.json`（值）＋ `config/schema/settings.json`（词表）；
  **跑一遍就生成**（不单开生成脚本，旧 `tools/gen_conf.py` 已删）。
  防漂移由 `tests/core/test_conf_projection.py` 承担（含子进程验证"退出即生成"）。
- [x] **接线**：`core.log.level` → `core.*` 这族记录器（导入内核即设）；`Kernel` 缺省策略向配置要值。
- [x] **文档**：`docs/architecture/config.md` 按实现重写、`index.md` 改"现行"、
  `docs/reference/config.md` 由声明现算重生成；`AGENTS.md` / `guides/development.md` /
  `rules/references/{docs,ui-boundary}.md` / `storage-design.md` 的旧路径与旧工具名同批改掉。
- [ ] **未来项（都不阻塞）**：
  ① **"流写" / 定时窗口落盘**——重启条件见 `decisions.md`（出现"长驻进程 + 外部读者要看到较新文件"）；
  ② **手写口 / 多来源合并**（个人覆写、部署覆盖）未做；
  ③ **值投影分文件**：十万行以内不分（作者定的量级标准），真要分再谈坐标；
  ④ `config/tables.yaml` 是表声明**本体**、待存储那轮经 `storage.db.tables` 接回，
     届时 `core/storage/tables.py` 的三表常量改成读它；
  ⑤ 库旋钮 `CAIRN_VAULT` / `CAIRN_THEME_DIR` / `CAIRN_SHAPES` 仍不进配置（随 App / UI 重建再定）。

## 内核重构（2026-09-22 立项；规格 `docs/architecture/kernel-spec.md`，2026-09-24 核对至 v1.4）

> ⚠️ 2026-09-29：`Core` / `Signal` / `Event` 等实现已随 `refactor/clean-local-code` 删除，本条仅存档。

> 性质变更：存储核心 + 通知 → **对象主干 + 事件对象**；对象集合 = 5 个；旧门户清理重做；`Vault` 解散。
> 分支 `refactor/kernel-object-core`（`e4f32ec` 骨架 → `878fcb1` M1 → `be704b2` M2/M3 →
> `b1e5995` 按作者口述重建 → `c35bebd` 引擎由内核自建 → `516e7e7` 收残留、全库转绿）。
> ⚠️ 2026-09-24 按代码核对落点：旧记的 `core/kernel/`、`core/tool/`、`VersionStore` **均已不存在**。

- [x] **M1 · 门户与实例管理**：落 `core/core.py` 的 `Core`（单例：两张对象表 + 引擎挂载 + `put`/`get`/`call`
  短面）、`core/signal/signal.py` 的 `Signal`（引擎 + `Subscription`）、`core/storage/engine.py` 的
  `Storage`（引擎角色：`store` / `get` / `fetch` / `drop` / `table` / `info_of`）、`core/conf`。
  `Vault` 已解散；旧 `core/signal`（`events` / `bus` / `service`）已删。
- [x] **M2 · `Event` 与解析器**：`core/types/event.py`（`Event` / `Action` / `Intent` / `Slot`）自包含编解码 +
  **网络往返**；`Signal` 解析包 → 按两张表取对象 → 逐步执行 action → 结果落槽。
  **注：`Topic`（多播声明）随重建一并移除**，现无独立多播机制，广播走 `core.send(Intent.*)`。
- [x] **M3 · 工具单元**：`Attr` / `Data` 落 `core/types/attr.py`、`@action` / `actions_of` 落
  `core/types/action.py`；**不在 `core/tool/`**（该层未成包，`topic` 未保留）。
- [x] **M4a · 对象不再私藏门户**：`Block` 的门户归属改**显式字段** `core`（+ `attach` / `detach` / `attached`），
  删掉 `_vault` 私有字段；**落盘一律显式 `core.put(data)`**（领域侧不再 `data.save()`），
  `Core.put` 负责挂门户 + 落视图。
- [ ] **M4b · 版本（卡口 Q7）· 现状比"归属待定"更缺**：**版本能力整体缺失**——
  `core/storage/version.py` 与 `VersionStore` 已不存在，`feature/note/versions.py` 只剩 `NoteCodec`
  （diff / apply / digest），**全库没有一处写版本表**；`Note` 只有 `save` / `persist`（注释：
  「版本由领域日后自建」），无 `history` / `body_at` / `restore`。
  另一处存储接触 = 领域表挂载（`feature/shared/relation.py` 走 `core.storage.table`）。
  **待作者裁定装回哪儿**：A 版本=存储能力（规格倾向）还是 B 域自带表（代码注释倾向）——见规格 §5.1。
- [x] **架构文档回写**：`kernel.md` / `ui-kernel.md` / `storage.md` / `domains.md` 已按新方向回写（`3369287`）。
- [ ] **信号复核（2026-09-26 按代码核对，作者问"信号是否已完善"）**：引擎与门户这条路是通的
  （`Signal` 解析 / 指挥 / 落槽 + `Subscription`；15 例 `tests/core/test_signal.py`；`Session` 真在订阅），
  但**三处"写了没接上"**——① `core/types/action.py` 的 `@action` / `actions_of` **全库无人调用**，
  `Signal.invoke` 是 `getattr` 直接打方法名，规格 §6.5 的"行动作表"未成立；
  ② `Intent` / `Action.action_type` / `Event.source`/`target` / `Slot` 未被引擎读取
  （`handle` 只判 `is_sendable`），§2.5 的"解析包 → 决策"退化成"全发"；
  ③ `Event` 无 canonical 编解码，网络往返（§4 (b)）只成立单机内存态。
  **作者已定：等配置与存储做完再动这三处**（别再另开一套机制）。
- [x] **Q5 · 工具单元边界**：已定——**只做构造与组合**；编排属"决策"、归 `Signal` 解析（真有用例再论）。
- [ ] **遗留**：Q3 `Data` 去留；Q2 门户强制程度；Q4 `Event` 因果链（网络侧再定）；Q7 版本装回哪儿。

## 底层（数据内核 + 通信主干 + UI 内核 + App）

> ⚠️ 以下条目按**旧主轴（存储核心）**记录；内核部分以 `kernel-spec.md` 为准，随 M2–M4 逐条清理。


### 数据内核 `core`
- [x] 存储底座 `Bucket` / `Block` / `catalog` / `version` / `table`；DB 重构切片 1–3
  （表列改名、`type` 整数码、`block.data` 收口、载体随机命名、去 `version_heads`、`relation.domain`、类型索引）。
- [x] ~~通信主干 `core/signal`（`events` / `bus` / `service`）；统一、静态挂载。~~ **已废弃**：随内核重建
  整体移除，现为 `core/signal/signal.py` 的引擎（`Signal` + `Subscription`）。
- [x] 类型 / 编解码；**`Vault` 已解散**（M1：持桶归 `Storage`，能力与实例管理归 `Core`）。
- [ ] `core/conf`：现仅 `core.py` 有常量，`feature` / `signal` / `storage` / `confsys` 待填。
- [ ] 数据库迁移机制（`catalog_version` → 旧库检测 / 迁移）。
- [ ] pack 压实 / gc。

### 领域 `feature`
- [x] note 拆「数据 `NoteData(Block)` + 域服务 `Note(Domain)`」；行编辑 / 关系。
  **版本已随内核重建移除**（只剩 `NoteCodec`），见上「内核重构 · M4b」。
- [x] **降级**：`Asset` / `Canvas` / `Group` 去 `Domain`，回归纯 `Block` 数据结构（构造入口在数据类）。
- [x] **最小类型表** `core/types/kind.py`：`TypeInfo{type, role, name, fields, deps, units}`，定义时登记。
- [x] **文件归位（第一批）**：`feature/shared/`（数据结构 / 值 / 设施）；`note/edit/` 三分（body/text/style）。
- [x] **`note/types.py` 拆包**：`body.py` / `data.py` / `service.py`（纯搬运）。
- [x] **操作归位**：编辑操作从 `NoteData` 迁到 `Note`（数据只留载体 + 读视图）。
- [x] **类型枚举**：`feature/shared/kinds.py` 的 `Kind` 分 `Feature` / `Data` 两支（去前缀、plain Enum）。
- [x] **数据描述合并**：`note/data.py`（`Style` 在 `edit/style.py`）；`Domain` 声明重定（name 模块路径、
  data 数据类、light 列表）；`Show` 落 `ui_tools/core/show.py`。
- [x] **文档回写**：`domains.md` 重写（域 / 数据两分支 + `Kind`）；`data-model.md` 类型名与 §12.2 映射表；
  storage / access / note-model / ui-kernel / ui-theme 的类型名与信号命名同步。
- [ ] 图片 / 音频转码（不传染库）；大正文透明分片（`Bucket.put_content`）。
- [ ] **跨域编排**（域间关系 / 订阅）——交由 App 承担，尚未落地。
- [ ] **变更签名**（非原作者 / `prev` 链；`alg` 日后换 `ed25519`）预留未实现。
- [ ] `note/shapes.py` 形状集 v2（含图形超出 / 图形未定义）未落。

### UI 内核 `ui_tools`（工具箱）
- [x] 声明树 `Node` / 注册表 / 元数据 / 路径；`compile` 管线 + Widgets 翻译器；atoms / list。
- [x] 配置 `Conf` / `Schema` / `apply_config`；绑定 `Bind` / `compile` + Qt 连接；`Session` / `Model` / `Bridge` /
  `QtListModel`；`Theme`。
- [x] `WindowHost` 根壳 + 路由；架构红线测试。
- [ ] 多页 Tab 宿主；配置 item 词表校验；主题文件系统（`config/theme/*.json`）；QML 岛承载器。

### App `src/app`
- [x] `Feature`（领域容器）；`win` 组合根 `CairnApp.open()/run()`；`__main__` 平台分发。
- [x] **根结构 = 大方框 + 格子 + 槽**：`CairnApp` 自己搭结构（顶带 / 主体 / 底栏 + `nav`/`main` 槽）；
  `NoteFacet` 提供 `nav`/`page` 部件、内容工具条 + 卡片舞台；真实笔记投影（`win/backend`）；
  卡片 / 详细两密度；主题从 `config/theme` 加载。
- [ ] **对象驱动生成**：领域对象 → `Facet` 自动出 `parts()`（nav / page / 卡片…；当前手写）。
- [ ] 顶带抽屉（搜索 / 命令之外的功能）；任务栏真实任务；边板（检查器 / 关系 / 版本）。
- [ ] 笔记编辑页（专注态）；镜头筛选（笔记 / 项目混排 + 颜色区分）。
- [ ] 毛玻璃真 Acrylic（DWM）与字体策略。
- [ ] 桌面打包：`packaging/cairn.spec` + 构建脚本。

## 编辑器 / 工具线（待 UI 外壳恢复后）
- [ ] 跨行选区 + 拖拽出视窗自动滚动。
- [ ] 撤销 / 重做栈。
- [ ] 添加型底层（表格 / 画板 / 多媒体）；查询型（查找替换）。
- [ ] 工具重排与持久化；笔记列表形态；画板绘制；多媒体拖入。

## 远期
- [ ] **Project（重）**：建在 block / body / bucket 之上；项目管理 + 类 GitHub 社区化；todo 验证器。
- [ ] 任务与进度、应用上下文。
- [ ] P2P / 服务端（顶层包待重设）、成员 / 社区、传输加密。

## 工程债
- [x] 架构文档回写：`storage.md`（表/列/随机 pack/无 heads）、`domains.md`（数据+域服务、路径）、
  `kernel.md`（§1.6 通信主干）、`data-model.md`（映射表 + 导引）、`ui-kernel.md` / `ui-theme.md` /
  `note-model.md` / `access.md` / `network.md` / `ecosystem.md`（现状导引、删旧 QML/Backend/net/server）。
  **全部与代码对齐**。
- [x] **SPDX 头自动化**（2026-09-24）：`tools/spdx.py`（`--check` / `--fix`）+ 根 `REUSE.toml`
  + pre-commit 钩子 + CI 步骤；208 个入库文件全合规。
  **编辑器层**（2026-09-25）：`.editorconfig` + VS Code 片段 / 任务 / 模板（`.vscode/`、`.fileTemplates.json`）。
  余项（不阻塞）：`LICENSES/Apache-2.0.txt` 未建（只有跑 `reuse lint` 才需要，而该 CLI 是 GPL、不引）。
- [ ] 可复现构建、代码签名（Authenticode）；包体瘦身。
- [ ] **CI / 构建改造（未完成；半成品已随旧分支删除，凭本条目重做）**：旧线
  `refactor/kernel-object-core` 上有一版草稿——用 `build.yaml`（可复用的构建矩阵）取代
  `build-windows.yml`，并把 `ocr-review.yml` 改名为 `agent-code-review.yml`（顺带去掉显式
  `pr_number` 入参）。草稿的 job 体是空的（只有一行 `call_workflows:`），带上会让 CI 直接红，
  故与分支一并删除；重做时按上面的意图重写，不要恢复那份草稿。
- [ ] Linux 服务端 / CLI / Docker（待服务端）。
- [ ] **OCR 评审 findings 清理**（进行中；⚠️ 2026-09-29 清单文件已随分支删除，条目仅存档）：
  原清单与分诊见 `docs/review/ocr-2026-09-22.md`（已删）；
  A 类分批批修已到 PR #18（第七批）、C 类档 1「删 / 简化 9 项」已落 PR #19；
  **清单表头仍停在 PR #16、计数待重算**（文件内勾选项 170：已勾 127 / 未勾 43）；余 B 类补文档、C 类待议。
  PR #20（内核重建）与 PR #21（配置引擎）的**新一轮评审**（65 条 + 49 条）已整改，
  见 `changes.md` 2026-09-26 两条。
- [ ] **PR #23（L0 存储重设计）评审线程**（2026-09-29 快照，进行中）：旧记的"仍有 13 条未整改"
  与代码不符。按 PR 的 **16 条未解决线程**逐条核对：**8 条已解决**（`_by_id` 已删、表内索引重名与
  解析口元素类型/非映射已校验、`active()` 已改为只 stat 并跳过坏载体、巡检已按摘要与坐标两项比对），
  已带证据关闭。**本轮整改 8 条**（见 `changes.md` 2026-09-29）：重建改名隔离、索引名带表名 +
  跨表重名校验、`Difference.subject`、`Index.open` 先解析后连接、空值归空串、封口线回 2 GiB、
  "槽数"两套口径分清、`iter_block_records` 文档如实。
  余 **1 条预留**：列举仍会读全库正文；去掉它要先把"块记录判据落成索引里的一列"
  （设计篇 §12 的 `body_addr` 字段问题，**待作者裁**，本轮不代裁）。
  旧清单里另有两条**不在**那 16 条线程内，已核实属实、均未修：`record.py` 的 ID 段**解两次**
  （`_payload_start` 量边界解一次，`decode` 又解一次同一段）；`TableSpec.signature()` 含 `doc`，
  即**注释文本参与声明投影**（`verify_declarations` 只在 `Vault.verify()` 里调、不在开库路径上，
  且 `open` 每次都 `align()` 重写 meta，故改注释不会打不开库，只是口径耦合）。
  另：`review`（第三方 OpenCodeReview）会因**安装抖动**失败（`ocr: command not found` /
  `Cannot find module '/usr/local/bin/ocr'`），与代码无关、重跑可自愈（2026-09-29 连失败两次、
  第三次通过）；该检查非 ruleset 必需项（只 `quality` 必需）。
