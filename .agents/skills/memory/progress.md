<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 进度 / TODO

> **只记「还没做 + 在做」**；做完的条目删掉。已定方向与理由在
> [`references/decisions/`](references/decisions/)，变更过程在 `git log`，两者都不在这里复述。

## 一、界面：Tauri + Web 前端（主线）

- [ ] **契约的类型同步（方向已定，实现未做）**：事实源取 **Python 侧声明**，链路分两段——
  登记表 → JSON Schema 由自己写确定性映射，JSON Schema → TS 取现成轮子
  （`json-schema-to-typescript` 一类，**许可须核实并写 `NOTICE`**）。
  生成物是"方法映射 + 一个泛型 `call`"，前端不手写 `interface`；入库 + `--check` 防漂移
  （同 `scripts/docgen.py` / `gen-tokens.mjs`）。**不引 pydantic**（会立第三套类型词汇）。
  **待领域类与命令面契约都定了再上马生成器**（没有调用方的生成器就是脚手架）。
- [ ] **标点范围是否扩到 `.ts/.rs`**：门禁已由报告模式改为就地替换，`.py` 于 2026-10-04 全量转换完毕
  （`punct` 实测命中 0 处）；`.md` 不动——纯中文正文的全角标点是正确排版。
- [ ] **待作者裁定 ·"页面层禁止原生标签与样式属性"**：这条最狠也最有效
  （让"边距圆角阴影一个都不写"从自觉变成没有位置可写）。认了我就写检查脚本接进门禁。
- [ ] **待作者裁定 · `knip`（未用导出与依赖）要不要接**（`jscpd` 已接，报告模式）。
- [ ] **规则扩展的触发条件**：`app/src/` 真的分出原子 / 组合 / 页面三层之后，
  再把"依赖只能向下"那条 dependency-cruiser 规则打开（**没有代码的规矩先不立**）。
- [ ] **许可证核对**：Tauri 及其插件、React 全链与后续每个前端依赖，核对后写进 `NOTICE`。
  目前**只确认 Tauri 是宽松型**（未取到 LICENSE 原文）；画布 / 富文本 / 表格是 AGPL 高发区。
- [ ] **卡片板余项**：拖动移动（现只有改大小与键盘移动）、卡片组（组本身可摆，
  **嵌套深度待裁**）、网格形状是否随窗口自适应、留洞还是补位的用户开关。
- [ ] **布局的壳侧命令**：`read_board_layout` / `write_board_layout` 现由前端降级到本地存储，
  等壳提供后换上（命令名与形状已定，见 `app/src/ipc/index.ts`）。
- [ ] **卡片类型清单**：笔记 / 待办 / 速记 / 集合 / 关系各是哪一种卡片，新卡片类型加在哪里。
- [ ] **其余 UI 相关项**：字号阶梯 / 品牌色 / 字体链 / 阴影 / 窗口装饰 / 图标 / 动效 /
  焦点与键盘 / 无障碍对比度 / 空态形态 / 窄窗网格 / 组件库选型 / 契约类型同步。
  观感口径见 `docs/architecture/ui_design/ui-theme.md`（草案），边界见
  `rules/references/ui-boundary.md`；旧稿 `by-design.md` 那份销账索引已不在库。
- [ ] 组件库与"难件"选型（编辑器、表格 + 虚拟滚动、画布）：**优先成品库，不自己造**。

## 二、入口：让项目跑起来

- [ ] **CLI 入口**：建库 → 存 → 列 → 取回 → 定位 → 摘块 → 回收，一条链路从命令行走通。
  现状：命令面（`core/api.py` 七个方法）与帧协议（`py_src/app/sidecar.py`）都已落地，
  缺的是一个**面向人的**命令行壳。**契约待作者裁定**：库根旋钮名、子命令集与退出码口径、
  以及是否就落在 `py_src/app/`。（曾按未获裁定的契约开工被叫停：重开须带作者已过的清单。）

## 三、内核余项

- [ ] **待裁 · 日志族名与配置键名不一**：记录器统一在 `cairn` 族，键名仍是
  `core.log.level`。改名要动值文件（`config/settings.json`）、生成页与文档示例；
  不改则留一处"键名与族名各说一套"。
- [ ] **事件日志的余项**：落点约定（如 `<root>/logs/events.jsonl`）**没有调用方**，
  等命令行落地时再定；轮转与上限、多进程同写一份文件的口径也未定。
- [ ] **未落地的内核机制**：
  **检索**；
  **回收的触发点**（回收这条路与它的判据都已落码：手动的 `sweep(engine)`、
  自动的 `reclaimable_bytes(engine)` 与阈值 `gc.auto.byte`，但**没有触发点**——
  命令面里没有它、也没有谁在后台定期问判据，谁在什么时候发起尚未定）。
- [ ] **本版本不设崩溃恢复**：属性槽原地覆盖，没有影子格、双缓冲与写前日志。
  一次覆盖崩在半路会留下半新半旧的属性槽，且**读侧看不出来**（crc32 只校验那一格自己）。
- [ ] **裁定篇的待裁项**（`docs/architecture/py_core/storage/block-parts.md` §10）：
  `birth_time` 是否落整数列（列表页排序与分页要用）、格长配置键该补的词
  （正文摘要链那一列的字段名与序列化已定：`body_history` ＋ JSON 数组）。
- [ ] **`Block.holds` 的去留**：它默认交空映射，当前没有读点（正表行的形状由
  `Engine.lay_index_row` 写）——删掉，还是留给领域层自定义，待作者确认。
- [ ] **迁移入口**：不做从载体重建，只随版本更新提供迁移；非版本更新期间自行改动造成的损坏，
  由使用者负责。格式与库结构变更时一律拒开旧库与老载体。
- [ ] **索引的查询面**：`IndexEngine.search` / `holders` / `count` / `field_names` 已可用，
  但**没有命令面入口**——界面按值查块、按正文查"谁在用它"这条路尚未接线。
- [ ] **按值查的两条待验**（接线时一并看）：按值查时已删块的正表行被滤掉
  （`Engine.read_index_rows` 按库里还有没有那一行判），而**正文索引那一行不带块的凭证**，
  故它不参与这一层过滤——那份正文还在不在由摘要链与 `gc` 判活；
  正文索引的位置行在回收里**行不搬、只换内容**（`gc._rehome_body` 写回同一格），
  索引块自己那一行照旧跟着搬、位置段跟着改写。
- [ ] **关系（预留 · 等调用方）**：现在没有任何领域产生关系，故**不预埋**。口径已定：
  **关系由块自己表达，库只做索引**（索引形状待设计）。将来落地时要定的是"块怎么把关系说出来"
  与索引怎么建——不是"库怎么存关系"。（原 `edge` 表已于 2026-09-30 删除。）
- [ ] **变更记录 / 版本（预留 · 已砍，等调用方）**：diff 那一摊已整条删除，判据是
  **零调用方即脚手架**。素材没丢：正文每次保存都是一份完整的、按内容地址去重的记录。
  重启时先答三问，见 `references/decisions/笔记.md` §四：① 什么算一次版本；
  ② 一步记什么（**只记动作不记内容**）；③ 链放哪儿（一个块 vs 一步一块，判据是格）。
- [ ] **多模态的二进制通道**：今天所有载荷走 base64 JSON 帧。按 `ui-boundary.md` §四
  "大载荷传句柄不传内容"，正解是前端持句柄、由壳侧按句柄取字节（原生资源协议 / 文件句柄），
  而非把内容塞进 JSON 帧。
- [ ] **文档站发布接线**（人工一次性）：Settings → Pages → Source 选 GitHub Actions。
- [ ] **书面语词典扩容**（持续）：只收歧义为零的标记；将来加 `docs/en/` 需补英文规则。
- [ ] **P2P / 服务端（未启动）**：`net` / `server` 两个顶层包已删除、待重设；
  成员 / 社区、传输加密都属于这一条线，与界面主线不共用通道，故不在这里展开。

## 四、界面层与领域层重建（待壳落地）

- [ ] **领域载荷的规范化字节层**（最关键的一条）：`py_src/model/note/format/` **不存在**。
  `cbor2` 编不出 dataclass，故 `NoteData.lines` 里放 `NoteLine` 对象时**存不下去**；
  今天能往返的只有标量属性与纯 JSON 值（如 `NoteTag.entries` 的 `dict[str, list[str]]`）。
  五个载体（`NoteData` / `NoteTag` / `NoteGroup` / `NoteAsset` / `NoteCanvas`）与值对象
  （`NoteLine` / `Span` / `Figure` …）的数据结构已落（见 `references/decisions/笔记.md` §四），
  缺的正是这一层把领域结构编成规范字节的能力。
- [ ] **中间层基座 + 领域服务**：延伸概念登记（短名 / 种类 / 用到哪些数据类）→ 命令装饰器
  → `Note` 服务（创建 / 修改 / 校验入口）→ 命令面接边车。口径见
  `references/decisions/领域.md` §二、§四。
- [ ] **领域活动日志**（业务语义的追溯："谁把哪条数据改成什么"）：与内核事件日志
  （`core/event/logs.py`，机制层的事实）分属两层，**没有代码**；落在领域层。
- [ ] 跨行选区 + 拖拽出视窗自动滚动；撤销 / 重做栈。
- [ ] 添加型底层（表格 / 画板 / 多媒体）；查询型（查找替换）。
- [ ] 工具重排与持久化；笔记列表形态；画板绘制；多媒体拖入。
- [ ] **文档回写余项**：`note-model.md` / `access.md` / `network.md` / `ecosystem.md`
  都已不在库（见 `docs/architecture/index.md` 的"尚未编写"一表），随各层回来时按当时的代码重写，
  并在 `mkdocs.yml` 的 `nav` 里登记。

## 五、工程债

- [ ] **重写 `scripts/build.py`**：现按 Qt 时代口径写（以旧的 Python 源码根为入口、
  PyInstaller + Inno），而外壳已改 Tauri + Python 边车。
- [ ] **CI / 构建改造**：`build.yaml`（可复用矩阵）取代 `build-windows.yml`；
  `ocr-review.yml` 改名 `agent-code-review.yml`（去掉显式 `pr_number`）。不要恢复旧草稿。
- [ ] **AI 评审未验证**：底座已切魔搭 API-Inference（按调用次数计的每日免费额度，超限 429），
  模型 `Qwen/Qwen3.8-27B`；待 `ocr llm test` 验证令牌与 Model ID 在架，并实测 tool calling
  与单次评审耗时（OCR 的流程完全依赖工具调用）——该模型仓的 `SupportApiInference` 字段此刻为 `false`，
  免费名单是否覆盖以实测为准。**否掉的两条路**：官方 DeepSeek API（调用量低，且按提示缓存命中
  计价的档位对评审负载不友好；原 key 失效返回 401）、本地 Ollama（下列实测边界）。
  Ollama 实测边界：可用 `qwen3.5:2b` / `qwen3.5:4b`（`qwen2.5-coder:3b` 无结构化 `tool_calls`）；
  上下文限 4096 token 且超长保留尾部、丢头部（须以 `OLLAMA_CONTEXT_LENGTH` 重启 serve）；
  RTX 3050 Laptop 约 10~12 token/s，并发降为 1；`reasoning.effort=none` 可关思考。
- [ ] 可复现构建、代码签名（Authenticode）、包体瘦身。
- [ ] Linux 服务端 / CLI / Docker（待服务端）。
- [ ] `LICENSES/Apache-2.0.txt` 未建（`reuse lint` 才需要，而该 CLI 是 GPL，不引）。
- [ ] docstring 覆盖补到 ≥95% 后，把 `scripts/docgen.py` 的 `DOCSTRING_MIN` 接成
  `--coverage --strict` 门禁。
- [ ] **中文搜索分词**（`jieba` 未引，本机构 sdist 失败）。
- [ ] **给上游 OnConf 提两个 issue**（本机未装 `gh`，待提）：① wheel 缺 `py.typed`
  （`pyproject.toml` 已声明 `Typing :: Typed`，实际包内没有，害得下游 strict 只能忽略它）；
  ② `EngineParams` 少了 `lock_timeout`，`conf(**engine)` 透传它会抛 `UnknownEngineParamError`。
  口径与后果见 `references/decisions/配置.md`「上游待办」。
- [ ] **配置键名与一道 AST 门禁**（从换引擎那次摘出来的独立任务）：八条键按
  `<架构层>.<功能域>.<对象>.<属性>` 改名（两份入库产物随之重生成）；门禁要管三件事——
  键必须是字面量、声明处的层前缀与文件位置一致、一个键只声明一处
  （最后一条正是 OnConf 不再提供的"重复声明即炸"，见 `references/decisions/配置.md`）。

## 六、远期

- [ ] **Project（重）**：建在块与内容之上；项目管理 + 类 GitHub 社区化；todo 验证器。
- [ ] 任务与进度、应用上下文。
