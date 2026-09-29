<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 提交规则

- 格式：Conventional Commits，描述用**中文**：`feat(ui): …`、`fix(core): …`。
- 提交前顺序固定：`uv run ruff check .` → `uv run mypy src tools tests` → `uv run pytest`。
- 提交前先看 `git status` / `git diff`，只暂存本次该提交的文件，别夹带无关改动。
- 具体消息生成流程见 `git-commit` 技能（来自 `github/awesome-copilot`，MIT）。

## 分支纪律（授权按分支区分）

隔离开发环境下，工作副本与用户的工作副本物理分离，Git 是唯一的同步通道。因此提交与推送的授权按分支划分：

- **默认分支 `main`**：只接受 PR。禁止直接推送、禁止强推、禁止删除。远端 ruleset 已强制该约束，缺少 PR 或 CI 未通过一律拒绝，不要尝试绕过。
- **自有分支 `ai/*`**：允许并要求自行 `commit` 与 `push`。自行提交属于正常流程，无须逐次征得同意；成果留在本地而未推送，视为任务未完成。
- **其他分支（`main`、`feat/*`、`refactor/*`、`docs/*` 等）**：只读。不提交、不 rebase、不强推、不改写历史。
- 任何情况下不得改动 git 配置与凭证（`user.*`、`core.sshCommand`、远端 URL、`gh` 登录态）。

## 何时需要用户确认

- 在 `ai/*` 分支上提交与推送：不需要，分支本身即授权范围。
- 合并入 `main`、修改远端规则、改写已推送历史、触碰其他分支：必须先征得同意。
- 用户未明确要求时，不得在非 `ai/*` 分支上提交。
