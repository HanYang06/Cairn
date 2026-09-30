<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 进度 / TODO

> **只记「还没做 + 在做」**；做完的条目删掉。已定方向与理由在
> [`references/decisions/`](references/decisions/)，变更过程在 `git log`，两者都不在这里复述。

## 一、界面：Tauri + Web 前端（主线）

- [ ] **三项前置未定，未定之前不得写界面代码**：契约的 Python ↔ TS 类型同步、
  外观令牌落地机制、前端工程宪法的落点（下一条）。
- [ ] **写 `rules/references/frontend.md`**：组件与样式规矩，**每条必须对应一道门禁**
  （判不了的规矩不写）。含"页面层禁止原生标签与样式属性"这条硬规矩（待拍板）。
- [ ] **前端门禁接线**（与 Python 七道同等地位，接进 pre-commit 与 CI）：
  `tsc --noEmit` / `biome check` / `vitest run` / `pnpm install --frozen-lockfile`，
  另加架构校验（`dependency-cruiser` 或 `eslint-plugin-boundaries`，**二选一**）、
  `stylelint` 的 `declaration-property-value-disallowed-list`、`jscpd`、`knip`、
  自写令牌防漂移检查。**命令名在壳第一次落地时写进 `package.json` 与规则文件。**
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
- [ ] **重写 `tools/build.py`**：现按 Qt 时代口径写（以 `src/app` 为入口、PyInstaller + Inno），
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
- [ ] docstring 覆盖补到 ≥95% 后，把 `tools/docgen.py` 的 `DOCSTRING_MIN` 接成
  `--coverage --strict` 门禁。
- [ ] 中文搜索分词（`jieba` 未引，本机构 sdist 失败）。
- [ ] 文档站发布接线（人工一次性）：Settings → Pages → Source 选 GitHub Actions。
- [ ] 书面语词典扩容（持续）：只收歧义为零的标记；将来加 `docs/en/` 需补英文规则。

## 六、远期

- [ ] **Project（重）**：建在 block / body 之上；项目管理 + 类 GitHub 社区化；todo 验证器。
- [ ] 任务与进度、应用上下文。
- [ ] P2P / 服务端、成员 / 社区、传输加密。
