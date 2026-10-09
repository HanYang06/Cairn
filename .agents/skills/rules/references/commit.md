<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 提交规则

- 格式：Conventional Commits，描述用**中文**：`feat(ui): …`、`fix(core): …`。
  **这条只是约定，本地不设钩子**（2026-10-10 撤掉 `commit-msg` 钩子与 `scripts/commitmsg.py`）：
  提交信息写偏不再被拦下，靠自觉与评审。
- 提交前顺序固定：一条命令跑完 —— `uv run pre-commit run --all-files`
  （13 个钩子，须先 `uv run pre-commit install`）；
  只跑 Python 侧时可用 `ruff check .` → `mypy py_src tools scripts tests` → `pytest`。
- 提交前先看 `git status` / `git diff`，只暂存本次该提交的文件，别夹带无关改动。
- 具体消息生成流程见 `git-commit` 技能（来自 `github/awesome-copilot`，MIT）。

## 分支纪律

- **默认分支 `main`**：只接受 PR。禁止直接推送、禁止强推、禁止删除。
  远端 ruleset 已强制该约束，缺少 PR 或 CI 未通过一律拒绝，不要尝试绕过。
- **其他分支**：正常工作分支，直接 `commit` 与 `push` 即可，无须逐次征得同意；
  **成果留在本地而未推送，视为任务未完成**。
- **合入 `main`、修改远端规则、改写已推送历史**：必须先征得作者同意。
- 任何情况下不得改动 git 配置与凭证（`user.*`、`core.sshCommand`、远端 URL、`gh` 登录态）。
