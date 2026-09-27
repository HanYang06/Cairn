<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 进度 / TODO

> 状态：进行中 / 已定 / 已废弃。完成后移入 `changes.md`，或直接删除。
> 细则以 `docs/architecture/*.md` 与代码为准，本文件只记「还没做 + 在做」。

## 存储重设计（2026-09-28 立项；第 1 阶段已落）

> 设计篇 = `docs/architecture/storage-design.md`（**L0 唯一事实来源**，草案 v1.1）。
> 方向见 `decisions.md`「存储重设计」。分支 `feat/storage-redesign`。
> **只跑局部测试**（作者口径：全量测试在当前阶段必然跑不通，等整体变更时统一规划）。

- [x] **片 0 · 设计篇**：`storage-design.md`（12 节）＋ `mkdocs.yml` 登记 ＋ 逐轮裁定
  （四层 / ID 两形态 / 记录自描述 / 单库多桶 / 表声明配置化 / 可重建分档）。
- [x] **片 1 · 身份层**：`core/types/id.py`（`Id` / `ValueUuid` / `ValueHash` / `SlotRange` / `Id.record`
  与 `Id.from_record`）＋ 存储侧异常（`StorageError` 与其 6 个子类）＋ `tests/core/test_id.py`（35 例）。
  一并：`types/ids.py` 里被取代的 `ID` 草稿删除（`Oid` / `Cid` 原样保留，待收口）。
- [x] **片 2 · 载体与记录层**：`core/storage/carrier.py`（槽布局与载体文件头）、
  `record.py`（记录头四项 + 编解码）、`io.py`（`CarrierFile`：追加写 / 按槽区间读 / 顺扫重建）
  ＋ `tests/core/test_carrier.py`（48 例，含篡改、截断、同槽记录错位）。
- [ ] **片 3 · 索引库**：`record` 表（`value_uuid` 主键 ＋ `value_hash` 非唯一索引）＋
  `bucket` / `edge` 表；表声明配置化（不写 SQL）；开库与挂载时对比与分档；重建档写进声明。
- [ ] **片 4 · 桶与多桶**：`Bucket` 接载体与索引库（替换 `catalog.db` 与旧 pack 逻辑）、
  桶目录与桶表、合并与短命桶。
- [ ] **片 5 · 收口**：`Oid` / `Cid` 与旧 `catalog.py` / `bucket.py` 旧逻辑退役、
  旧篇 `storage.md` 与 `data-model.md` 存储态章节清理、全量测试与记忆整理。
- 遗留 · `block.py` / `bucket.py` / `catalog.py` **本阶段一字未改**（仍走旧路径）；
  `core/storage/__init__.py` 已同时导出新旧两套，**暂并存**。

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
  由 `schema/settings.json` **整页生成**（入库，`--check` 防漂移进 CI）；
  `--coverage` 出 docstring 覆盖报告。**规则：能算的就不写、能查的就不写。**
- [ ] **片 3 · docstring 覆盖补齐（有缺口，勿忘）**：公共类 / 函数 **579 个、117 个没 docstring
  （79.8%）**，因 `show_if_no_docstring: false` 而**从 API 页静默消失**。
  缺口最大：`core/storage/catalog.py` 24、`feature/shared/canvas.py` 13、`feature/note/tools.py` 12。
  补到 ≥95% 后把 `tools/docgen.py` 的 `DOCSTRING_MIN` 接成 `--coverage --strict` 门禁。
- [ ] **片 4 · 内容补齐（随实现走）**：`docs/architecture/` 各篇仍是「草案」，**随内核落地逐步回写**；
  用户手册等界面稳定后再写（现在不假装有）。
- [ ] **片 5 · 中文搜索**：`jieba` 分词未引（本机构 sdist 失败）；需要时补，属构建期依赖。
- [ ] **片 6 · 发布接线（人工一次性）**：仓库 Settings → Pages → Source 选 **GitHub Actions**；
  之后 `main` 的文档变更自动发布到 <https://hanyang06.github.io/cairn/>。自定义域名暂不需要。
- [ ] **可选**：多语言（zh/en）站点；依赖图 / 类型表等更多"从代码投影"的页面（`docgen.py` 已有落点）。

## 配置引擎（2026-09-26 立项；片 1–2 已落）

> 方向见 `decisions.md`「配置（2026-09-26 定）」：声明即事实、两个投影落盘、取值三条。
> **先做配置、再动存储、最后补信号**（作者定的顺序）。

- [x] **片 1 · 引擎与投影**：`core/types/cfg.py`（`Cfg` 声明/取值）、`core/conf/`（engine + schema +
  errors + params）、`core/storage/conf.py`（存储那组声明，**各管各的**）、`tools/gen_conf.py`（`--check`）、
  `tests/core/test_conf.py`（19 例，含重名检查、接线与端到端投影一致）、`docs/architecture/config.md`。
  投影：`config/settings/core/{conf/params,storage/conf}.json` ↔ `schema/settings/…` + `schema/settings.json`
  （hub 默认 `settings`；重名检查拒写别人的文件）。
- [x] **片 2 · 接线**：`BucketConfig` 的默认值改由声明供值（`storage.block.max_bytes` /
  `storage.pack.max_blocks` / `storage.pack.max_bytes`，`__post_init__` 按声明补齐，已建桶把值存目录、
  重开读回）；`core.log.level` 在导入 `core` 时设到 `core.*` 这族 logger（不劫持 root）。
  一并：`db__engine.py`（空骨架 + 多一个下划线）删除，等 `DB` 设计定了再落。
- [ ] **片 3 · 手写口 / 校验**：第二个 hub（个人覆写 / 多 hub 合并）；可选 `jsonschema` 校验；
  `gen_conf.py --check` 进 pre-commit / CI。
- [ ] **遗留**：`storage.version.retention_days` 已登记**未接线**（版本能力本身待 Q7 裁定后装回）；
  环境旋钮 `CAIRN_VAULT` / `CAIRN_THEME_DIR` / `CAIRN_SHAPES` 暂不进配置（开发 / 部署入口，测试靠它重定向）。

## 内核重构（2026-09-22 立项；规格 `docs/architecture/kernel-spec.md`，2026-09-24 核对至 v1.4）

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
- [ ] **OCR 评审 findings 清理**（进行中）：清单与分诊见 `docs/review/ocr-2026-09-22.md`；
  A 类分批批修已到 PR #18（第七批）、C 类档 1「删 / 简化 9 项」已落 PR #19；
  **清单表头仍停在 PR #16、计数待重算**（文件内勾选项 170：已勾 127 / 未勾 43）；余 B 类补文档、C 类待议。
  PR #20（内核重建）与 PR #21（配置引擎）的**新一轮评审**（65 条 + 49 条）已整改，
  见 `changes.md` 2026-09-26 两条。
