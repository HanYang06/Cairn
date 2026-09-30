<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 进度 / TODO

> **只记「还没做 + 在做」。** 做完的条目**删掉**，不改 `[x]` 留作历史；
> 变更过程见 `git log`。已定的方向与理由在 [`references/decisions/`](references/decisions/)，
> 不在本文里复述。

## 一、界面材质转换：Qt → Tauri + Web 前端（**当前主线**）

> 决定的现状与理由见 [界面](references/decisions/界面.md)；
> 可执行约定见 `rules/references/ui-boundary.md`。
> 作者口径：**先把规则与规范定清楚，再动手搭**——为防止架构偏移与重复实现。

- [ ] **三项前置未定，未定之前不得写界面代码**：
  ① **契约的 Python ↔ TS 类型同步**（事实源放 Python 还是中立 schema；两处边界会把类型洗两遍）；
  ② **外观令牌的落地机制**（CSS 自定义属性 vs 声明生成令牌模块）；
  ③ **前端工程宪法的落点**（下一条）。
- [ ] **前端工程宪法与门禁（防架构腐蚀，先于第一行前端代码）**：
  ① 写 `rules/references/frontend.md`——组件与样式规矩；**头一条原则是"能机器判定的规矩才写成规矩"**，
  判不了的（如"组件设计得好不好"）不许写进去，否则规则本身就是垃圾桶；
  ② 每条规矩**必须对应一道门禁**（无门禁的规矩不写）；
  ③ **样式一致性靠结构消灭，不靠自觉**：样式绑进组件、上层只做组件编排、
  **边距 / 圆角 / 阴影一律不写**；为此加"页面层禁止原生标签与样式属性"这条硬规矩（待作者拍板）；
  ④ 门禁候选（都属行业成熟做法，不必自研）：`dependency-cruiser` 或 `eslint-plugin-boundaries`
  （**二选一**，架构校验）、`stylelint` 的 `declaration-property-value-disallowed-list`
  （禁硬编码色 / 圆角 / 间距字面量）、`jscpd`（重复代码）、`knip`（未用导出与依赖）、
  自写令牌防漂移检查（照 `tools/prose.py` 与 `docgen.py` 的形状）。
- [ ] **工程门禁接线**：前端的 `tsc --noEmit` / `biome check` / `vitest run` /
  `pnpm install --frozen-lockfile` 与上面的架构与样式检查，接进 pre-commit 与 CI，
  与 Python 七道同等地位。**具体命令名在壳第一次落地时写进 `package.json` 与规则文件**。
- [ ] **许可证核对**：Tauri 及其插件、React 全链、以及后续每一个前端依赖逐个核对并写进 `NOTICE`。
  目前**只确认 Tauri 是宽松型，未取到 LICENSE 原文**，按 `licensing.md` 不得视为已核实。
  画布 / 富文本 / 表格三类是 AGPL 高发区，采用前先查。
- [ ] **落地顺序（草案，待作者认可）**：壳与前端骨架可运行（窗口 + 三栏 + 一条真实数据）→
  令牌落地 → 列表 / 编辑器 / 画布等"难件"选型。**每一片都要能真跑起来**，不推半成品。
- [ ] `docs/architecture/ui-theme.md` §2.1 回写：令牌机制一经裁定即回写该节，
  并在 `ui-boundary.md` §三同步。
- [ ] **组件库与"难件"选型**（编辑器、表格 + 虚拟滚动、画布）随界面生长再定，
  判据是**优先成品库、不自己造**。

## 二、让项目跑起来（作者要求；与界面转换并行）

> 现状：**内核之外没有任何入口**——`pyproject.toml` 里连 `[project.scripts]` 都没有。
> 内核是 Qt-free 的，故"能跑"**不依赖界面材质**，可以先单独兑现。

- [ ] **CLI 入口**：恢复命令入口，用一条真实链路证明内核回路（建库 → 存 → 列 → 取回 →
  定位 → 摘块 → 巡检）能从命令行走通。
- [ ] **契约待作者裁定**：库根旋钮名（`CAIRN_VAULT` 一类）、子命令集与退出码口径、
  `src/app/` 是否作为命令行落位。
  **注意**：本项曾按未获裁定的契约起草并开工，被作者叫停（零字节落盘）；
  重开时必须带上**作者已过的命令面清单**。

## 三、内核余项（重建已收口，见 [内核](references/decisions/内核.md)）

- [ ] **待作者裁 · 版本能力装回哪儿**（形态 A 存储提供 / 形态 B 领域自带）。
- [ ] **待作者裁 · 摘块与巡检的相互作用**：`drop` 只摘行、记录留在载体里，
  于是巡检把它报成 `missing_row`、处置又补回来（等于撤销摘块）。
  消掉它要么引入墓碑，要么等压实回收落地。
- [ ] **待作者裁 · 列举仍会读全库正文**：去掉它要先把"块记录判据落成索引里的一列"。
- [ ] **未来项**：压实回收（删内容要判引用）、跨行事务与崩溃恢复、批量写入合并通知、
  大正文分片、检索、P2P / 服务端（顶层包待重设）。
- [ ] **依赖盘点**：`blake3` / `argon2-cffi` / `cryptography` / `fastcdc` / `pyyaml` / `tomli-w`
  在 `src/` 与 `tools/` 里**一处引用都没有**；裁掉能缩短安装与供应链面，
  留着的理由是各自的上层（分片、配置引擎、传输加密）还要回来。

## 四、界面层重建余项（待壳落地后）

- [ ] 跨行选区 + 拖拽出视窗自动滚动；撤销 / 重做栈。
- [ ] 添加型底层（表格 / 画板 / 多媒体）；查询型（查找替换）。
- [ ] 工具重排与持久化；笔记列表形态；画板绘制；多媒体拖入。
- [ ] **领域层重建**（`src/feature/`）：类型词表随领域层重建再定
  （plain `Enum`、值即落盘字符串）。
- [ ] 文档后续（不阻塞）：`domains.md` / `note-model.md` / `access.md` / `network.md` /
  `ecosystem.md` 描述的是尚未重建的层，各层重建时按实现回写。

## 五、工程债

- [ ] **入库词表可能被"只认得一部分配置"的进程整份覆盖**（待作者裁）：
  `core/conf/registry.py` 的 `_flush` 只在"一个键都没有"时不动词表；
  只导入 `core`（不导入 `core.storage.conf`）的进程退出时会把
  `config/schema/settings.json` 改写成只有 `core.*` 那三条。**2026-09-30 实测发生**，
  已还原；触发命令未定位（`pytest` / `prose` / `spdx` / `mypy` 逐个验过都不改它）。
  修法待裁：词表更新**只增不删**（与 `tablegen.sync` 同款），或按登记面判完整性。
- [ ] `tools/build.py` 仍按 Qt 时代的打包口径写（docstring 声称"UI 外壳回来之后修回"，
  而外壳已改为 Tauri + Python 边车）：**待随壳第一次落地重写**，不许按旧口径修。
- [ ] **CI / 构建改造**：用 `build.yaml`（可复用构建矩阵）取代 `build-windows.yml`，
  并把 `ocr-review.yml` 改名为 `agent-code-review.yml`（去掉显式 `pr_number` 入参）。
  旧草稿的 job 体是空的，带上会让 CI 直接红，**不要恢复那份草稿**。
- [ ] **AI 评审当前不可用，暂转人工**：本地 `deepseek-flash` 的 key 已失效（`ocr llm test` 返回 401）。
  若改走本地 Ollama，实测边界是：可用模型仅 `qwen3.5:2b` / `qwen3.5:4b`
  （`qwen2.5-coder:3b` 无结构化 `tool_calls`，不可用）；**上下文被限制在 4096 token 且超长时
  保留尾部、丢弃头部**，须以 `OLLAMA_CONTEXT_LENGTH` 重启 serve 方可提升；
  RTX 3050 Laptop（4 GiB）实测约 10~12 token/s，**并发须降为 1**；
  `qwen3.5:4b` 默认开思考，`reasoning.effort=none` 可关（`think=false` 无效）。
- [ ] 可复现构建、代码签名（Authenticode）；包体瘦身。
- [ ] Linux 服务端 / CLI / Docker（待服务端）。
- [ ] `LICENSES/Apache-2.0.txt` 未建（只有跑 `reuse lint` 才需要，而该 CLI 是 GPL、不引）。
- [ ] 文档体系：**docstring 覆盖补齐**（公共类 / 函数缺 docstring 者会从 API 页静默消失）；
  补到 ≥95% 后把 `tools/docgen.py` 的 `DOCSTRING_MIN` 接成 `--coverage --strict` 门禁。
- [ ] 文档体系：**中文搜索**（`jieba` 未引，本机构 sdist 失败；属构建期依赖，需要时再补）。
- [ ] 文档体系：**发布接线（人工一次性）**：仓库 Settings → Pages → Source 选 GitHub Actions。
- [ ] 书面语词典扩容（持续）：只收**歧义为零**的标记；候选是泛用动词「搞」系与
  非正式省略的收尾语气，均需先确认歧义再收。将来加 `docs/en/` 时需补英文口语规则。

## 六、远期

- [ ] **Project（重）**：建在 block / body 之上；项目管理 + 类 GitHub 社区化；todo 验证器。
- [ ] 任务与进度、应用上下文。
- [ ] P2P / 服务端、成员 / 社区、传输加密。
