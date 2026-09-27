<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 网络层（P2P 底层）规格

> 承接 [`storage-design.md`](./storage-design.md)（桶 / 块 / 目录）与 [`access.md`](./access.md)（传输加密 / 档位）。
> 定位：**网络是增强层，不是本体**。本地永远可用；联网只是把块连起来。

状态：**草案 v0.2**（未实现；已按「无 manifest、内容按 `checksum` 寻址」修订术语，落地前整体复核）

> **2026-09-19**：**未实现**的预留设计；原实验顶层包 `src/net` / `src/server` 已删除，落地时重设。
> 存储层已就绪（内容寻址），本层只是把块连起来。

---

## 1. 分层视图

```
应用/服务层      同步、博客、社区治理        ← 上层（后做）
────────────────────────────────────────
数据面协议       want / meta / block          ← 本文件核心
节点角色         server（中心化·联邦共享） · peer（去中心化）
传输 / 安全      py-libp2p + Noise/TLS
发现 / NAT       mDNS · bootstrap · DHT · AutoNAT · Relay v2 · DCUtR
编址             checksum(内容) · id(块身份)
身份             传输身份 Ed25519 + X25519（未来引入）
存储             桶 / 块 / 目录（已有）
```

**关键：底层已具备。** 内容是按 `body_hash` 寻址的，P2P 只需回答"我要这些内容哈希，本地是否有？"
——这是最小原语。

---

## 2. 编址

| 目标 | 地址 |
|---|---|
| 内容 | `checksum`（BLAKE3 十六进制，本库内容池去重键） |
| 块身份 | `id`（OID / ULID） |
| 对端 | libp2p `PeerID`（由传输身份公钥派生） |

- 内容寻址使"任意节点都能提供任意内容"成立，无需中心目录。
- 一个对象的内容位置由**目录行**给出：`id → checksum → 内容`；分享策略决定**谁可请求、谁可提供**。

---

## 3. 数据面协议（草案）

最小、面向流、可校验。协议 ID 前缀 `cairn/1`：

| 协议 | 方向 | 作用 |
|---|---|---|
| `/cairn/1/want` | 请求方 → 提供方 | 发一组缺失 `checksum`，请求内容 |
| `/cairn/1/block` | 双向 | 传块内容（远端可加密，逐块可校验） |
| `/cairn/1/meta` | 请求方 → 提供方 | 取块行元信息（`id` / `type` / `checksum`） |
| `/cairn/1/announce` | 双向 | 公告"我有哪些 id"（可选，走 GossipSub） |

流程（**pull 为主**）：

```
A: meta(id)            → 拿到块行（type / checksum）
A:  验块签名 + 作者
A: want([本地缺失的 checksum...])
                       → B: block(逐块流式回传)
A:  逐块：checksum 重算校验 → 落桶
```

- **对象即流**：大内容由分片块 + 索引块构成，可分段、并行、断点续传。
- **增量**：按内容哈希只传本地缺失的块。
- **校验**：`checksum` 重算 + 块签名 + 版本 `prev` 链。

---

## 4. 传输 / 安全

- 传输：**py-libp2p**（QUIC / TCP / WebSocket）。
- 信道加密：**Noise / TLS**（libp2p 内建）+ 传输 / 远端副本的 AEAD（本地不加密，见 `access.md`）。
- 身份：**传输身份** Ed25519 / X25519（未来引入），PeerID 由公钥派生。
- 信任：块签名是信任根；内容寻址只在明文 / 密钥可见范围内泄漏相等性（`access.md` §2）。

---

## 5. 发现 / NAT

| 场景 | 机制 |
|---|---|
| 同局域网 | **mDNS** |
| 广域网引导 | bootstrap 节点 / rendezvous |
| 大规模路由 | **Kad-DHT** |
| 可达性探测 | **AutoNAT** |
| 直连失败兜底 | **Circuit Relay v2** |
| 打洞升级 | **DCUtR** |
| 公告/订阅 | **GossipSub** |

**诚实边界**：对称 NAT 下打洞失败属常态，必须走中继——这是互联网性质，不是缺陷。

---

## 6. 选型与成熟度（澄清）

- **协议层成熟**：打洞/中继/探测是 libp2p 标准，go/rust/js 久经考验。
- **Python 绑定**：py-libp2p（MIT/Apache）已过实验期，功能齐全、可用；但未到 go-libp2p 的实战年限。
- **决策**：**先用 py-libp2p**（纯 Python、省心），协议设计不押注具体实现；撞瓶颈再考虑 **go/rust-libp2p 边车 + IPC**。

---

## 7. Server 与 P2P 的关系（优先级）

```
Server（中心化 · 联邦共享）  —— 更底层、优先级更高
   │  天然携带公网节点
   ▼
P2P（去中心化）              —— 由 server 衍生
   └─ relay / bootstrap / 打洞协调 直接复用 server 的公网节点（无额外自建成本）
```

- **server 是基础通信**：中心化，但**联邦共享**（多个 server 可互通）。
- **P2P 是衍生**：去中心化，但**不自建打洞节点**——server 的公网节点兼任 relay/bootstrap/rendezvous。
- **共同前提**：先能**互联**，数据底层通信先立住。
- 结论：**server 优先级 ≥ P2P；先做互联与 server，再做 P2P。**

---

## 8. 分阶段实现

| 阶段 | 目标 | 依赖 |
|---|---|---|
| **P0** | 单节点 server：能被连、按 `want/block` 提供块 | 存储层（已就绪） |
| **P1** | 两节点互联同步：head 拉取 + 权限档过滤 | access 层 |
| **P2** | server 作公网节点：bootstrap / Relay / AutoNAT | py-libp2p |
| **P3** | P2P 打洞（DCUtR），复用 server 公网节点 | P2 |
| **P4** | 公告/发现：GossipSub + DHT | P3 |

**先 P0**：不碰公网、不碰 NAT，先证明"内容寻址 + want-list + 互联"这条最小链路。

---

## 9. 隐私边界

- 默认**不广播"我有什么"**；只响应请求。
- 元数据（谁连谁、传多少、何时）仍会泄漏，要藏需上 PIR/洋葱路由——不在本阶段。
- 档位决定可提供范围：私密不对外，公共仅限成员，公开可全网。

---

## 10. 待定

1. want-list 的批大小与背压策略。
2. 是否引入"块打包"减少小对象往返。
3. 权限档在协议层的具体表达（能力令牌 vs 会话协商）。
4. server 的联邦协议（多 server 如何互认与同步）。
5. 传输实现：先用 py-libp2p，还是先写最小 TCP 协议验证再换。
