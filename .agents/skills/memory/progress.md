<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 进度 / TODO

> **只记「还没做 + 在做」**；做完的条目删掉。已定方向与理由在
> [`references/decisions/`](references/decisions/)，变更过程在 `git log`，两者都不在这里复述。

## 一、界面：Tauri + Web 前端（主线）

- [x] **外观令牌的落地机制**（2026-09-30 定 + 已落）：`config/theme/tokens.json` 唯一手写处 →
  `app/scripts/gen-tokens.mjs` 生成 `app/src/styles/tokens.css`（入库、防漂移）；
  组件只引用 `var(--…)`，由 stylelint 拦字面量。**只剩"页面层禁原生标签"那条待拍板。**
- [ ] **契约的类型同步（方向已定，实现未做）**：事实源取 **Python 侧声明**，链路分两段——
  登记表 → JSON Schema 由自己写确定性映射（`conf` 的类型词表到 JSON Schema 近 1:1），
  JSON Schema → TS 取现成轮子（`json-schema-to-typescript` 一类，**许可须核实并写 `NOTICE`**）。
  生成物是"方法映射 + 一个泛型 `call`"，前端不手写 `interface`；入库 + `--check` 防漂移
  （同 `scripts/docgen.py` / `gen-tokens.mjs`）。**不引 pydantic**（会立第三套类型词汇）。
  **待笔记的真领域类落地后才上马生成器**（没有调用方的生成器就是脚手架）。
- [x] **前端门禁接线**（2026-09-30 定 + 已落）：`app/` 里一条 `pnpm check` 跑完七道——
  类型（tsc）/ lint 与格式（Biome）/ 样式（stylelint）/ 架构（dependency-cruiser）/
  令牌防漂移 / 重复代码（jscpd，报告模式）/ 单测（Vitest）。**已接进** pre-commit
  （只在 `app/` 变动时跑）与 CI 的 `web` job。**已实测会拦**：页面里直接 import Tauri API 被
  `ipc-single-chokepoint` 拦下。
- [ ] **待作者裁定 · 标点全量替换**：`scripts/punct.py` 已接（**报告模式**），全仓 `.py` 里
  注释与 docstring 的中文标点约 **5300 处**。待定：是否一次性 `--fix`、是否改成阻断式、
  范围是否扩到 `.ts/.rs`（`.md` 建议不动——纯中文正文的全角标点是正确排版）。
- [ ] **待作者裁定 ·"页面层禁止原生标签与样式属性"**：这条最狠也最有效
  （让"边距圆角阴影一个都不写"从自觉变成没有位置可写）。认了我就写检查脚本接进门禁。
- [ ] **待作者裁定 · `knip`（未用导出与依赖）要不要接**（`jscpd` 已接，报告模式）。
- [ ] **规则扩展的触发条件**：`src/` 真的分出原子 / 组合 / 页面三层之后，
  再把"依赖只能向下"那条 dependency-cruiser 规则打开（**没有代码的规矩先不立**）。
- [ ] **许可证核对**：Tauri 及其插件、React 全链与后续每个前端依赖，核对后写进 `NOTICE`。
  目前**只确认 Tauri 是宽松型**（未取到 LICENSE 原文）；画布 / 富文本 / 表格是 AGPL 高发区。
- [x] **壳与前端骨架**（2026-10-01 落在分支 `feat/app-skeleton`，工作树 `Cairn-app`）：
  卡片工作台骨架已跑起来——**整数格网格吸附（拖右下角改大小）· 消重叠 · 自动补位 ·
  键盘（方向键移动 / Shift + 方向键改尺寸）· 布局落盘 · 字体三层替换 · 浅色纸面 + 暖金**。
  46 条单测（含新增的"令牌引用必须存在"与布局不变量两块）＋ 七道门禁全绿。
  **未做**：**拖动卡片移动**、卡片组、布局的壳侧命令（现落本地存储）、内容面（等契约生成器）。
- [ ] **卡片板余项**：拖动移动（现只有改大小与键盘移动）、卡片组（组本身可摆，
  **嵌套深度待裁**）、网格形状是否随窗口自适应、留洞还是补位的用户开关。
- [ ] **布局的壳侧命令**：`read_board_layout` / `write_board_layout` 现由前端降级到本地存储，
  等壳提供后换上（命令名与形状已定，见 `app/src/ipc/index.ts`）。
- [ ] **卡片类型清单**：笔记 / 待办 / 速记 / 集合 / 关系各是哪一种卡片，新卡片类型加在哪里
  （判据沿用 `ui-kernel.md` §4.2 的"加一处"验收指标）。
- [ ] **其余 UI 相关项**：销账清单收在 `docs/architecture/by-design.md` §9 的一张索引里
  （字号阶梯 / 品牌色 / 字体链 / 阴影 / 窗口装饰 / 图标 / 动效 / 焦点与键盘 /
  无障碍对比度 / 空态形态 / 窄窗网格 / 组件库选型 / 契约类型同步）。
  **问"UI 还剩什么"就看那张表**，不另记一份。
- [ ] 组件库与"难件"选型（编辑器、表格 + 虚拟滚动、画布）：**优先成品库，不自己造**。

## 二、入口：让项目跑起来

- [ ] **CLI 入口**：建库 → 存 → 列 → 取回 → 定位 → 摘块 → 巡检，一条链路从命令行走通。
  **契约待作者裁定**：库根旋钮名、子命令集与退出码口径、`src/app/` 是否作命令行落位。
  （曾按未获裁定的契约开工被叫停，零字节落盘；重开须带上作者已过的命令面清单。）

## 三、内核余项

- [ ] **块范式再往前一步（目标形态已写成文档，待新对话执行）**：见
  [`docs/architecture/block-model.md`](../../docs/architecture/block-model.md)（草案）。
  要点：声明即赋值（删 `attr` 标记与 `indexed=`）、`ID(self)` 带持有者且**表名取自 ID**、
  `Body` 退成值（绑定靠取值）、`AttrIndex` 改成登记在册的块并新增同构的 `BodyIndex`
  （`derived`、只在索引库）。**当前代码是"零参探针 + 标记分类"那一版**（见
  [`内核.md`](references/decisions/内核.md) §七）；差异逐条列在该文 §6，执行顺序见 §7，三项待裁见 §9。
- [ ] **变更记录 / 版本（预留 · 已砍，等调用方）**：diff 那一摊已整条删除
  （`types/diff.py`、动作词表、`notediff` 表点名淘汰），判据是**零调用方即脚手架**。
  素材没丢：正文每次保存都是一份完整的、按内容地址去重的记录。重启时先答三问，见
  `references/decisions/笔记.md` §四：① 什么算一次版本；② 一步记什么（**只记动作不记内容**）；
  ③ 链放哪儿（一个块 vs 一步一块，判据是槽位）。
- [ ] **关系（预留 · 等调用方）**：现在没有任何领域产生关系，故**不预埋**。口径已定：
  **关系由块自己表达，库只做索引**（索引形状待设计）。将来落地时要定的是"块怎么把关系说出来"
  与索引怎么建——不是"库怎么存关系"。（原 `edge` 表已于 2026-09-30 删除。）
- [ ] **只在库里的结构（预留 · 等真实需求）**：即"不进载体、只活在库里的表"。
  开关**放在表声明上**（就是 `tier: source`），**不做成块里的字段**——那个字段本身要落盘，
  而它恰恰不落盘。真要做需配三样：不经载体的写入口、巡检/重建知道跳过它、备份覆盖它。
  **判据（防它变成第二个数据库）：能用块表达的一律用块**，只有"推不出来又必须跨块查"的结构才配。
- [ ] **待裁 · 声明文件只增不减**：`config/tables.yaml` 的形状更换（改名 / 删列）目前只能
  **整份重生成**（删文件再跑一遍），没有生成脚本。
- [ ] **版本与可变身份（方向已定，细节未定）**：**不新增内核机制**，锚写在领域数据类自己的
  `attr` 里（与 `docs/architecture/storage-design.md` §9.1「版本不属于存储」一致）。
  细节待定：`prev` 链 / 取 `birth_time` 最大 / 领域真源表。口径见 `references/decisions/领域.md` §三、§五。
- [ ] **"用 ID 的角色"目前只用到一半**：形状收下了块上所有持有 `ID` 的字段名（`_Shape.ids`），
  但引擎只用 `id` 那一条决定"这个类型建不建表"；其余角色（指向别处的指针）要落成引用列，
  得先有"这个 ID 指向哪张表"的声明。等第一个真调用方出现再做（不预埋）。
- [ ] **块一律零参构造再赋值**：声明在 `__init__` 里、形状由零参探针现算，故
  `NoteData(title=…)` 这类带参构造不成立。要更便捷须另想一条"声明与传值分离"的路子（不预埋）。
- [ ] **待裁 · 列举仍会读全库正文**：先把"块记录判据落成索引里的一列"。
- [ ] 未来项：压实回收（删内容要判引用）、跨行事务与崩溃恢复、批量写入合并通知、
  大正文分片、检索、P2P / 服务端（顶层包待重设）。
- [ ] **陈旧 docstring 与口径不符**（改实现时漏回写，属"文档回写是任务的一部分"这条债）：
  ① `core/storage/rows.py` 与 `index.py` 里仍有提"关系边"的措辞，而 `edge` 表已于 2026-09-30 删除；
  ② `core/init.py` 的 docstring 说领域表"不进声明文件"，而 `tablegen.sync` 实际会把
  **登记过的全部类型**（含领域表）写进同一份 `config/tables.yaml`。
- [ ] **依赖盘点**：`blake3` / `argon2-cffi` / `cryptography` / `fastcdc` / `pyyaml` / `tomli-w`
  在 `src/` 与 `tools/` 里一处引用都没有。其中 **`blake3` 已被明确否掉**（算法取
  `uuid4()` + `sha256`），**`fastcdc` 也不再有用处**（媒体定了固定粒度分片、不上 CDC）——
  这两个建议直接撤掉声明。

## 四、界面层与领域层重建（待壳落地）

- [ ] **笔记的内容模型**：**数据结构已落**（`model/note/types/`，口径见
  `references/decisions/笔记.md` §四）——五个载体（`NoteData` / `NoteTag` / `NoteGroup` /
  `NoteAsset` / `NoteCanvas`）＋值对象（`NoteLine` / `Span` / `Figure` …），一律"继承 `Block`
  + 在 `__init__` 里声明"。**待落**：`model/note/format/`（载荷的规范化字节——
  没有它，`Body(...)` 声明的字段还只停在内存里，落盘仍走 `kernel.store(bytes…)`）。
- [ ] **多模态的硬缺口**：二进制通道**未接线**（今天所有载荷走 base64 JSON 帧）。
  按 `ui-boundary.md` §四"大载荷传句柄不传内容"，正解是前端持句柄、由壳侧按句柄取字节
  （原生资源协议 / 文件句柄），而非把内容塞进 JSON 帧。
- [ ] 跨行选区 + 拖拽出视窗自动滚动；撤销 / 重做栈。
- [ ] 添加型底层（表格 / 画板 / 多媒体）；查询型（查找替换）。
- [ ] 工具重排与持久化；笔记列表形态；画板绘制；多媒体拖入。
- [ ] **领域层重建**（`py_src/model/`）：**架构与数据结构都已落**（见 `references/decisions/领域.md`
  与 [`内核.md`](references/decisions/内核.md) §七）——块声明范式换成"继承 + 在 `__init__` 里声明"，
  笔记五个载体与值对象已迁；接入面已通（`attr` / `Body` 声明 → 形状探针 → 类型登记 → 块记录载荷）。
  待落：中间层基座（延伸概念登记 / 命令装饰器）→ `Note` + `NoteData` 服务 → 载荷编解码
  （`model/note/format/`）→ 命令面接边车。
- [ ] **文档回写余项**：`note-model.md`（仍是草案，正文模型那一套已由
  `references/decisions/笔记.md` 取代）/ `access.md` / `network.md` / `ecosystem.md` 随各层回写。
  2026-10-01 已回写：`domains.md`（数据标准形）、`data-model.md`（扩展方式两条）、
  `reference/glossary.md`、`api/core.md`、`guides/development.md`。

## 五、工程债

- [ ] **待裁 · 入库词表被部分进程整份覆盖**：`core/conf/registry.py` 的 `_flush` 只在
  "一个键都没有"时不动词表；只导入 `core` 的进程退出会把 `config/schema/settings.json`
  改写成只有 `core.*` 那三条。**2026-09-30 实测发生**，已还原；触发命令未定位。
  修法：词表更新**只增不删**，或按登记面判完整性。
- [ ] **重写 `scripts/build.py`**：现按 Qt 时代口径写（以 `src/app` 为入口、PyInstaller + Inno），
  而外壳已改 Tauri + Python 边车。
- [ ] **CI / 构建改造**：`build.yaml`（可复用矩阵）取代 `build-windows.yml`；
  `ocr-review.yml` 改名 `agent-code-review.yml`（去掉显式 `pr_number`）。不要恢复旧草稿。
- [ ] **AI 评审暂不可用**（本地 key 失效，401），暂转人工。若走本地 Ollama，实测边界：
  可用 `qwen3.5:2b` / `qwen3.5:4b`（`qwen2.5-coder:3b` 无结构化 `tool_calls`）；
  上下文限 4096 token 且超长保留尾部、丢头部（须以 `OLLAMA_CONTEXT_LENGTH` 重启 serve）；
  RTX 3050 Laptop 约 10~12 token/s，并发降为 1；`reasoning.effort=none` 可关思考。
- [ ] 可复现构建、代码签名（Authenticode）、包体瘦身。
- [ ] Linux 服务端 / CLI / Docker（待服务端）。
- [ ] `LICENSES/Apache-2.0.txt` 未建（`reuse lint` 才需要，而该 CLI 是 GPL，不引）。
- [ ] docstring 覆盖补到 ≥95% 后，把 `scripts/docgen.py` 的 `DOCSTRING_MIN` 接成
  `--coverage --strict` 门禁。
- [ ] 中文搜索分词（`jieba` 未引，本机构 sdist 失败）。
- [ ] 文档站发布接线（人工一次性）：Settings → Pages → Source 选 GitHub Actions。
- [ ] 书面语词典扩容（持续）：只收歧义为零的标记；将来加 `docs/en/` 需补英文规则。

## 六、远期

- [ ] **Project（重）**：建在 block / body 之上；项目管理 + 类 GitHub 社区化；todo 验证器。
- [ ] 任务与进度、应用上下文。
- [ ] P2P / 服务端、成员 / 社区、传输加密。
