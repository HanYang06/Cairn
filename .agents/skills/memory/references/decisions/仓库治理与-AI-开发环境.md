<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

## 仓库治理与 AI 开发环境（2026-09-28 定 + 已落）

- 已定 · **`main` 只接受 PR**：GitHub ruleset「Protect main」（匹配 `~DEFAULT_BRANCH`）在原有
  `deletion` / `non_fast_forward` / `code_quality` 之上，加入 `pull_request` 与 `required_status_checks`
  （必需检查仅 `quality`，`strict_required_status_checks_policy=false`）；`bypass_actors` 为空，
  规则对 admin 同样生效。
  | 理由：**约束目标 ref，而非约束动作**。本地合并是纯客户端行为，服务端不可见，任何本地钩子都可被
  `--no-verify` 或改写 `core.hooksPath` 绕过；且 `pre-merge-commit` 对快进合并不触发（分支自 `main`
  拉出、`main` 期间未动时合回即快进，不产生合并提交）。改为约束 ref 后，快进 / 合并提交 / rebase /
  cherry-pick / 网页与 API 直改一律归约为「更新 `refs/heads/main`」，全部拒绝；合法写入只剩服务端 PR 合并。
- 已定 · **不设「禁止本地合并」规则**：该约束在 Git 中无法成立，且会误伤「把 `main` 合入特性分支」
  这一正当操作。规则只针对合入 `main` 的方向。
- 已定 · **`build` 与 `deploy` 不作必需检查**：`docs.yml` 与 `build-windows.yml` 的 job 同名 `build`
  且带 `paths` 过滤，未触及相应路径的 PR 永远等不到该检查，会使 PR 长挂等待；`deploy` 仅在 `main` 上运行。
- 待定 · **`required_approving_review_count` 现为 0**：GitHub 不允许自批，待 AI 首个 PR 由作者人工批准后
  再升至 1。升至 1 之前，不得声称存在人工评审闸门。
- 已定 · **AI 使用独立 GitHub 账号**（`AcvCva`，仓库协作者角色 = `write`，非 admin）：
  身份分两层——**提交身份**（`user.name` / `user.email`，用 `<id>+<login>@users.noreply.github.com`
  保证归属）与**推送身份**（SSH key / token）。硬约束只在第二层；`admin` 可修改 ruleset，
  等于把锁交给被约束者。
- 已定 · **AI 的工作台 = 独立 WSL 发行版 `cairn-ai`**：`[automount] enabled=false`、
  `[interop] appendWindowsPath=false`；Linux 用户 `ai` 不入 `sudo` 组、密码锁定；
  仓库克隆位于 Linux 文件系统（`/home/ai/cairn`）。
  | 理由：① WSL 默认把 `C:\` 挂到 `/mnt/c` 且以宿主 Windows 身份访问，不切断则隔离为零
  （宿主私钥无口令，可直接读取）；② 关闭 automount 只挡默认挂载，`drvfs` 属 WSL 机制，
  持有 root 者可自行挂回，故承重件是「无 sudo」；③ 克隆置于 `/mnt/*` 之外，避免 9p 的 I/O 开销。
  实测：无 drvfs 挂载、`/mnt/c` 为根分区内的空目录、读取宿主私钥报 `No such file or directory`、
  `sudo` 组为空且 sudoers 仅授予 `%sudo`。
- 已定 · **可见性靠 Git，不靠共享目录**：AI 分支统一 `ai/` 前缀；任务收尾必须推送，未推送视为未完成；
  用户侧以 `git fetch` + `git diff HEAD...origin/ai/*` 或 PR 评审查看，另有
  `\\wsl.localhost\cairn-ai\...` 供只读浏览其工作树。
  | 理由：两个写者共用一个工作树会互相破坏（切换分支卷走未提交改动、`stash` 互相覆盖、
  提交夹带对方半成品）；分仓后「是否可见」等价于「是否已推送」，属可检查的事实。
- 已定 · **提交授权按分支划分**（细则在 `rules/references/commit.md`）：`ai/*` 上自行 `commit` + `push`
  无须逐次同意，`main` 只经 PR，其他分支只读。
- 已知前提 · 隔离成立的前提是 **agent 进程运行在 `cairn-ai` 内**（由 WSL 终端启动）。
  若仍由 Windows 侧会话驱动，则仅多出一套 Linux 工具链，隔离不成立。
