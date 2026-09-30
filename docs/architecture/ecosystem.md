<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 生态调研：第三方选型与自研边界

> 目标：逐项给出「需求 → 现成实现 → 语言 → 许可 → 采用建议」，通用能力优先复用成熟的第三方实现。
> 原则：**通用组件优先复用；核心能力自研。**

状态：**草案 v0.1**。标注「需核实」的条目，落地前必须再查一次许可证/成熟度。

---

## 0. 结论速览

| 需求 | 现成实现 | 语言 | 许可 | 采用 |
|---|---|---|---|---|
| P2P 网络 | **py-libp2p** | Python | MIT/Apache | ✅ 首选（未引入） |
| AI 接入 | **MCP Python SDK** | Python | MIT | ✅ 首选（未引入） |
| 富文本/块编辑 | **ProseMirror / Tiptap** | JS/TS | MIT | ✅ Web 面 |
| 手绘画布 | **Excalidraw** | TS | MIT | ✅ Web 面 |
| 笔迹平滑 | **perfect-freehand** | JS | MIT | ✅ |
| 形状识别 | **$P 模板识别**（自实现）/ 端侧小模型 | Py/JS | 自造 | ✅ 先模板后模型 |
| 全文检索 | **SQLite FTS5** | C/Py | 公有领域 | 未实现（检索为预留） |
| 协作 CRDT | **Yjs** | JS | MIT | ⏸ 后置（未引入） |
| 画布 SDK（备选） | tldraw | TS | **需核实（疑商用授权）** | ⚠️ 谨慎 |
| 矢量几何 | shapely | Py | BSD | ✅ 备用 |
| 哈希 / 序列化 | blake3 / cbor2 | Py | Apache-2.0 / MIT | cbor2 已用；blake3 声明未用 |

自研清单：hub / 载体存储（已落地）、笔记行模型（行身份 + 区间样式）、关系 / 衍生、索引 / 反链、界面外壳（Tauri 壳 + Web 前端，`app/`）、AI 工具暴露方式。

---

## 1. 编辑 / 正文格式

| 项目 | 语言 | 许可 | 说明 |
|---|---|---|---|
| ProseMirror | JS/TS | MIT | 无头富文本与文档模型，生态最成熟 |
| Tiptap | JS/TS | MIT（部分 pro 扩展付费） | 封装 ProseMirror 的开发接口，降低接入成本 |
| Lexical | JS/TS | MIT | Meta 出品，现代编辑器框架 |
| Slate | JS/TS | MIT | 可定制，生态范围较小 |
| Excalidraw | TS | MIT | 手绘风白板 / 画布，可作画布底座 |
| tldraw | TS | **需核实（tldraw license，免费版疑带水印）** | 画布 SDK，能力较强但许可受限 |
| perfect-freehand | JS | MIT | 点序列 → 平滑笔画形状 |
| rough.js | JS | MIT | 手绘风格图形 |
| Qt 原生 | Py/C++ | LGPL/商业 | `QTextEdit` / `QGraphicsView`；已作废：Qt 已退场，界面路线为 Tauri 壳 + Web 前端 |

**建议**：数据格式用本仓库的**行序列 + 区间样式**（CBOR，见 [`note-model.md`](./note-model.md) §6），编辑器的文档 JSON 只作**投影 / 输入**。

- 界面既定路线为 **Tauri 壳 + Web 前端**（`app/`）；Qt 时代构件（`ui_tools` / `src/app`）已随 2026-09-29 的重建删除。富编辑与画布库按 Web 生态评估，当前均未引入。
- Web 编辑面的选型：块编辑用 `ProseMirror`（或 Tiptap）；自由手绘用 `Excalidraw`（MIT，避开 tldraw 的许可风险）+ `perfect-freehand`。
- **逻辑图（diagram）：自造**——只存数值序列（图形 + 连线），布局与连线派生（`data-model.md` §5.2）；`Excalidraw` 是**自由画布**，不适合语义图。

---

## 2. 手绘 → 标准形状（形状识别）

| 方案 | 说明 | 建议 |
|---|---|---|
| `$1 / $N / $P` 识别器 | 模板匹配，学术经典，易移植 | ✅ 首选，覆盖线 / 三角 / 圆 / 箭头 |
| 端侧小模型（ONNX Runtime） | 更高精度，可离线 | 次选：模板精度不足时启用 |
| Google QuickDraw / sketch-rnn | 数据/模型重 | ❌ 过重 |
| shapely / numpy | 几何拟合、简化、规整 | ✅ 辅助 |

**建议**：先实现 `$P` 模板识别（纯 Python/JS 皆可），完成「手绘笔画 → 标准图元」的转换；精度不足时再引入端侧小模型。
注意：**sketch 存原始笔画，识别是可选增强**（不阻塞保存），识别结果只作附加产物（见 `note-model.md` §6.1）。逻辑图（diagram）不需要识别。

---

## 3. 协作 / CRDT（后置）

| 项目 | 语言 | 许可 | 说明 |
|---|---|---|---|
| Yjs | JS | MIT | 最成熟，配 `y-prosemirror`/`y-excalidraw` |
| Automerge | Rust + JS | MIT | 历史/时间旅行强；**Python 绑定成熟度需核实** |
| diamond-types | Rust | MIT | 高性能 CRDT |

**建议**：实时协作本阶段**不做**（`note-model.md` 已后置）。将来若做，Web 编辑器侧选用 `Yjs`，集成成本最低。

---

## 4. 本地优先同步 / P2P

| 项目 | 语言 | 许可 | 状态 |
|---|---|---|---|
| **py-libp2p** | Python | MIT/Apache | 未引入（`uv.lock` 无此依赖）；调研结论：已过实验期，QUIC/TCP/WebSocket、Noise/TLS、mDNS、Kad-DHT、GossipSub、中继、打洞齐全 |
| go/rust-libp2p | Go/Rust | MIT/Apache | 更成熟更快，但要引入非 Python 进程 |
| Hypercore / Dat / Willow | JS/Rust | MIT（多数） | 另一类本地优先复制，绑定参差 |
| IPFS | Go/Rust | MIT | 理念相近，偏重 |

**建议**：**py-libp2p 作为 P2P 底座首选**（本节是该选型与许可的事实源，`network.md` §6 指向此处）。存储层已是内容寻址，P2P 层只需「want-list = 一组 `checksum`」加 libp2p 传输，两者直接对应。性能不足时再评估 go / rust 实现。

---

## 5. AI 接入

| 项目 | 语言 | 许可 | 说明 |
|---|---|---|---|
| **MCP Python SDK**（`mcp`） | Python | MIT | 把能力暴露成 tools，生态广（各类 MCP 客户端） |
| 自定义 skill 协议 | — | — | 无生态，需自造 |

**建议**：用 **MCP Python SDK** 把内核现有能力暴露为 tools——存储的写入与读取（`store` / `load` / `drop`，见 [`kernel.md`](./kernel.md) §3）与事件订阅（`bus.subscribe`，事件目录见 [`kernel.md`](./kernel.md) §2）。建关系属预留（关系尚未落地，`storage-design.md` §12）。这一形态印证 `note-model.md` 的立场：**AI 不是作者，是工具调用者**；低能力 AI（规则）与高能力 AI（大模型）都走同一工具集。

---

## 6. 检索 / 索引

| 项目 | 语言 | 许可 | 说明 |
|---|---|---|---|
| SQLite FTS5 | C | 公有领域 | 随 SQLite 可用；检索当前未实现（`storage-design.md` §12 标为预留） |
| tantivy（tantivy-py） | Rust | MIT | 全文能力更强；FTS5 不足时再评估 |
| jieba / 分词 | Python | MIT | 中文分词（FTS5 中文需处理） |

**建议**：检索落地时首选 FTS5；中文检索用分词预处理或 trigram；FTS5 能力不足时再评估 tantivy。

---

## 7. 先前作品（读，不 fork）

| 项目 | 与我们关系 | 可借鉴 |
|---|---|---|
| Anytype / any-sync | 最近：本地优先+加密+P2P+对象图（许可**需核实**） | 数据模型、同步思路 |
| AppFlowy | Flutter+Rust，Notion 类 | 编辑器 UX、块模型 |
| SiYuan | 本地优先、块、SQLite | 索引/块结构 |
| Logseq | outliner、文件本体 | 双链、daily note UX |
| Obsidian | 闭源，插件生态 | UX 范式 |

**结论**：**读它们的数据模型与 UX，不 fork**（存储基础不同：明文文件 vs hub / 载体的内容寻址，见 `note-model.md`）。

---

## 8. 分工总账

分工以 §0 结论速览为准：采用清单与自研清单同表一处。

---

## 9. 待核实清单

1. tldraw 许可（免费版是否带水印、商用条件）。
2. Anytype / any-sync 许可是否 OSI。
3. Automerge 的 Python 绑定成熟度。
4. Excalidraw 作为可嵌入 SDK 的成熟度与体积。
5. MCP Python SDK 的当前 API 形态（tools/resources/prompts）。
