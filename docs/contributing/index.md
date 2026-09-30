<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 贡献

Cairn 尚在早期，**提交前请先读**「[约定与红线](../guides/conventions.md)」——那里有几条硬红线
（许可、SPDX、分层），违反会被 CI 拦截。

## 怎么参与

| 我想…… | 去哪 |
|---|---|
| 搭环境、跑测试 | [参与开发](../guides/development.md) |
| 确认某个词的含义 | [术语表](../reference/glossary.md) |
| 了解设计理由 | [架构文档](../architecture/index.md) |
| 查某个类 / 函数的签名 | [API 参考](../api/index.md) |
| 改文档 / 加一页 | [怎么改文档](docs.md) |
| 确认许可与署名要求 | [许可与署名](license.md) |

## 提交约定（摘要）

- **commit message 用中文 + Conventional Commits**：`feat(core): …` / `fix(ui): …` / `docs: …`。
- **只有维护者明确要求时才 commit**；不要自作主张提交。
- 提交前跑：`uv run pre-commit run --all-files`（11 个钩子，清单见
  `rules/references/quality.md` §4）。**钩子需先装**：
  `uv run pre-commit install --hook-type pre-commit --hook-type commit-msg`。
- CI（`.github/workflows/ci.yml`）会再跑一遍全量门禁，含覆盖率 ≥ 80%。

## 报告问题

仓库：[github.com/HanYang06/cairn](https://github.com/HanYang06/cairn)。
描述问题时**带上能复现的最小步骤**；涉及数据的问题请说明库根路径（`CAIRN_VAULT`）与操作序列，
但**不要附带真实笔记内容**。
