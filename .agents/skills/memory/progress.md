<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 进度 / TODO

> **只记「还没做 + 在做」**；做完的条目删掉。已定方向与理由在
> [`references/decisions/`](references/decisions/)，变更过程在 `git log`，两者都不在这里复述。

## 一、界面：Tauri + Web 前端（主线）

- [x] **外观令牌的落地机制**（2026-09-30 定 + 已落）：`config/theme/tokens.json` 唯一手写处 →
  `app/scripts/gen-tokens.mjs` 生成 `app/src/styles/tokens.css`（入库、防漂移）；
  组件只引用 `var(--…)`，由 stylelint 拦字面量。**只剩"页面层禁原生标签"那条待拍板。**
- [ ] **待作者裁定 · 契约的类型同步**：领域契约必须同时是 Python 与 TS 的类型。
  倾向"单一事实源 + 生成"（仓内先例：`scripts/docgen.py`）；事实源放 **Python** 还是 **中立 schema**。
  **生成器要有真领域类才有对象可生成**，而 `feature` 层当前为空，故本项**不预先实现**
  （没有调用方的生成器就是脚手架）。
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
- [ ] **壳与前端骨架**（作者自办环境；落地顺序草案）：窗口 + 三栏 + 一条真实数据 →
  令牌落地 → 列表 / 编辑器 / 画布选型。每片都要能真跑起来。
- [ ] `docs/architecture/ui-theme.md` §2.1 回写（令牌机制裁定后），并同步 `ui-boundary.md` §三。
- [ ] 组件库与"难件"选型（编辑器、表格 + 虚拟滚动、画布）：**优先成品库，不自己造**。

## 二、入口：让项目跑起来

- [ ] **CLI 入口**：建库 → 存 → 列 → 取回 → 定位 → 摘块 → 巡检，一条链路从命令行走通。
  **契约待作者裁定**：库根旋钮名、子命令集与退出码口径、`src/app/` 是否作命令行落位。
  （曾按未获裁定的契约开工被叫停，零字节落盘；重开须带上作者已过的命令面清单。）

## 三、内核余项

- [ ] **关系（预留 · 等调用方）**：现在没有任何领域产生关系，故**不预埋**。口径已定：
  **关系由块自己表达，库只做索引**（索引形状待设计）。将来落地时要定的是"块怎么把关系说出来"
  与索引怎么建——不是"库怎么存关系"。（原 `edge` 表已于 2026-09-30 删除。）
- [ ] **只在库里的结构（预留 · 等真实需求）**：即"不进载体、只活在库里的表"。
  开关**放在表声明上**（就是 `tier: source`），**不做成块里的字段**——那个字段本身要落盘，
  而它恰恰不落盘。真要做需配三样：不经载体的写入口、巡检/重建知道跳过它、备份覆盖它。
  **判据（防它变成第二个数据库）：能用块表达的一律用块**，只有"推不出来又必须跨块查"的结构才配。
- [ ] **待裁 · 声明文件只增不减**：`config/tables.yaml` 的形状更换（改名 / 删列）目前只能
  **整份重生成**（删文件再跑一遍），没有生成脚本。且 `Kernel.create` 直接持 `tables_path`
  这个引用，测试夹具对 `core.storage.tables.tables_path` 的 monkeypatch 拦不住它——
  跑一次用例就会把仓根的声明文件追加改写（已实测发生，已重生成）。
- [ ] **待裁 · 版本能力装回哪儿**（A 存储提供 / B 领域自带）。
- [ ] **待裁 · 摘块与巡检相互作用**：`drop` 只摘行，巡检把它报成 `missing_row`、处置又补回来；
  消掉要么引入墓碑，要么等压实回收。
- [ ] **待裁 · 列举仍会读全库正文**：先把"块记录判据落成索引里的一列"。
- [ ] 未来项：压实回收（删内容要判引用）、跨行事务与崩溃恢复、批量写入合并通知、
  大正文分片、检索、P2P / 服务端（顶层包待重设）。
- [ ] **依赖盘点**：`blake3` / `argon2-cffi` / `cryptography` / `fastcdc` / `pyyaml` / `tomli-w`
  在 `src/` 与 `tools/` 里一处引用都没有。

## 四、界面层与领域层重建（待壳落地）

- [ ] 跨行选区 + 拖拽出视窗自动滚动；撤销 / 重做栈。
- [ ] 添加型底层（表格 / 画板 / 多媒体）；查询型（查找替换）。
- [ ] 工具重排与持久化；笔记列表形态；画板绘制；多媒体拖入。
- [ ] **领域层重建**（`src/feature/`）：类型词表随领域层重建再定。
- [ ] `domains.md` / `note-model.md` / `access.md` / `network.md` / `ecosystem.md` 随各层回写。

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
