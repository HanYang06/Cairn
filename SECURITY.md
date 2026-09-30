<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 安全策略

## 报告漏洞

发现安全问题**不要开公开 issue**。走 GitHub 的私密渠道：

1. 仓库页 `Security` 标签 → `Report a vulnerability`（GitHub 私密漏洞报告）；
2. 或者用 [SECURITY 联系邮箱](mailto:jihanyang123@163.com)，标题前缀 `[cairn-security]`。

请在报告里给出：受影响的版本或提交、复现步骤、影响面判断（能读数据 / 能执行代码 / 仅信息泄露）、
以及期望的公开时间。我们会在**七个工作日内**首次回复。

## 支持范围

只维护**最新发布**与 `main` 分支。历史版本不打补丁。

## 这个项目的威胁模型（写清楚，免得误报）

Cairn 是**本地优先**的桌面应用，威胁面比服务端窄，但也因此有几条边界值得说明：

| 面 | 现状 | 相关口径 |
|---|---|---|
| **网络监听** | **本地内核不开任何端口**；内核 ↔ 壳只走 stdio 帧 | `rules/references/ui-boundary.md` §四 |
| **前端权限** | 前端**没有文件系统权限**（Tauri capabilities 不授予 fs 范围） | 同上 |
| **壳的边界** | 壳只做窗口与系统；**不写业务**，也不解构领域字段 | 同上 §一 |
| **本地加密** | **不加密**（设计取舍）。故别在库里放密钥 | `docs/architecture/storage-design.md` §9.5 |
| **第三方依赖** | Apache-2.0 项目，**禁 GPL / AGPL**；依赖逐个核许可证 | `rules/references/licensing.md` |

**不构成漏洞的常见项**：

- 「前端能读到库内容」——设计如此，前端本来就要渲染内容；关键是**前端不碰磁盘、只经 IPC**。
- 「本地任意程序能读写库文件」——不是本项目的安全边界：库是**用户自己机器上的普通文件**，
  权限交给操作系统。真要防同机攻击者，属操作系统层的事。
- 「导出 / 备份文件里含明文」——同上，见「不加密」。

## 自动化检测（已接线，见 `.github/workflows/`）

| 检查 | 何时跑 | 拦什么 |
|---|---|---|
| **CodeQL**（`codeql.yml`） | push 到 main · PR 到 main · 每周一 | 跨文件污点传播（Python / JS-TS） |
| **dependency-review**（`ci.yml`） | 每个 PR | **本次改动新增**的有漏洞依赖 |
| **pip-audit**（`ci.yml`） | push 到 main · 手动 | Python 依赖的已知 CVE |
| **pnpm audit**（`ci.yml`） | push 到 main · 手动 | 前端依赖的已知 CVE |
| **gitleaks**（`ci.yml`） | push 到 main · 手动 | 提交历史里的密钥 / 令牌 |
| **ruff `S` 族**（`ci.yml`） | 每个 PR | 单文件里的危险写法（类 bandit） |

**还有两处建议在仓库设置里打开**（属设置项、不在文件里，故在此记下）：

1. **Secret scanning + Push protection**：本仓库为公开仓库，GitHub 免费提供。
   与 gitleaks 的区别是它在**推送时**就挡，而 gitleaks 是推送之后扫。
2. **Dependabot alerts**（漏洞告警）与 **security updates**（自动提补丁 PR）。
   `dependabot.yml` 管的是"版本更新"，这两项管的是"漏洞告警"，**互不替代**。
