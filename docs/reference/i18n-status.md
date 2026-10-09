<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 译文状态

本站的语言口径（2026-10-10 作者定）：

- **中文是事实基础**（`docs/**/*.md`，挂在 `/`）——它是作者亲手写的：术语、设计页与路线图
  都以中文成稿。
- **英文是机器翻译的产物**（`docs/**/*.en.md`，挂在 `/en/`）——目标是由 CI 的翻译模型产出，
  不逐页手写。

构建遵循的判定因此只看扩展名：**带 `.<locale>` 后缀的文件是译文，不带后缀的归默认语言。**
"谁是事实源"不再需要每次判断——**不带后缀的那一份就是**。

这是一条正当的国际化：**产品对外以英文可用，但作者用母语写作**。代价落在根路径上——
英文读者进站先看到 `/` 的中文页，靠顶栏的语言选择器切换；选择器**停在当前页**，
不会把人丢回首页。

> **当前 6 页英文是手写的**（本页与首页、向导三页、贡献页），机翻流程尚未接线；
> 接线后**默认不覆盖已存在的英文页**，只补缺失的那些，除非显式重译。

## 已译清单

| 页面 | 中文（事实源） | 英文 |
|---|---|---|
| `index` | ✅ | ✅ |
| `guides/quickstart` | ✅ | ✅ |
| `guides/development` | ✅ | ✅ |
| `guides/conventions` | ✅ | ✅ |
| `contributing` | ✅ | ✅ |
| `reference/i18n-status` | ✅（本页） | ✅ |
| `reference/glossary` | ✅ | — |
| `reference/config` | ✅（生成页） | — |
| `architecture/index` | ✅ | — |
| `architecture/storage-design` | ✅ | — |
| `architecture/block-model` | ✅ | — |
| `architecture/py_core/config` | ✅ | — |
| `architecture/py_core/storage/block-parts` | ✅ | — |
| `architecture/py_core/storage/pack-format` | ✅ | — |
| `architecture/py_core/storage/query-path` | ✅ | — |
| `architecture/ui_design/ui-theme` | ✅ | — |
| `roadmap/1.x` | ✅ | — |
| `roadmap/index` | ✅ | — |
| `api/index` | ✅ | — |
| `api/core` | ✅（生成页） | — |

**架构、路线图与 API 三类故意排在最后**：它们的措辞还在动，译一个即将重写的页面等于写两遍。
架构与 API 页也多是贴着代码的表述，英文读者对照[术语表](glossary.md)可以直接读原文。

没有英文对应页的页面，在 `/en/` 下**由中文原文渲染**（即 `fallback_to_default`）。
英文站不缺页面，只是其中有部分仍是中文，而页面本身**不带标记**说明这一点——
上表就是那个标记。

## 一页怎么译

1. 先写或先改**中文**页（`docs/path/page.md`）。**它是原文**，术语在那里定下。
2. 英文由 `scripts/translate.py` 用**机器翻译**产出为 `docs/path/page.en.md`
   （阿里云机器翻译通用版，`TranslateGeneral`；RPC 签名用标准库自己算，**不引 SDK**）。三条硬约束写在脚本里：
   - **只译正文**：围栏代码块整块保留，行内代码、链接、图片与裸 URL 先摘成占位符再放回
     （一译就断链、坏锚点）；表格分隔行不动；
   - **增量译，不从头来**：每次只处理"**缺英文页**"或"**英文页落后**"的那些页，
     已一致的页**一个字符都不送**。故译文一旦落库，后续运行只花增量；
   - 单次请求上限 5000 字符，故按行分段；**产出开 PR**，术语那一轮由人过一遍。

> **"落库"是这一步的目的**：译文只有进了 `main` 才算持久化。`translate.yml` 补译后
> **自动提交到独立分支并开 PR**——PR 一合，那些 `.en.md` 就是版本库里的事实，
> 下一次运行会跳过它们。**没有"每次从 0 翻"这回事**，前提是 PR 要合。
> 中文改了而英文没跟上时，生成器会**只重译那一页**（判据与 `--check` 同一套）。
> 手写的那几页（没有摘要行）默认不动；想让它们也纳入漂移追踪，跑一次 `--stamp`
> 补上摘要行（只补行，不重译正文）。
3. 在 `mkdocs.yml` 的 `nav:` 里登记一次（**不写语言后缀**）；英文导航另在
   `i18n` 插件的 `languages[en].nav` 下加一条。
4. 跑 `uv run mkdocs build --strict`。语言选择器与 `hreflang` 链接由 `i18n` 插件生成，
   不手写任何 URL。

```powershell
uv run python scripts/translate.py --list      # 报账：哪些页待译、多少字符
uv run python scripts/translate.py --check     # 门禁：英文落后于中文即非零退出
uv run python scripts/translate.py             # 译"缺失或落后"的页
uv run python scripts/translate.py --stamp     # 只给手写英文页补摘要行（不重译）
uv run python scripts/translate.py --force     # 全部重译（连已一致的）
```

**额度与设置**：机器翻译通用版对**主账号每月 100 万字符**免费，超出 50 元/百万字符。
本站中文原文约 9.5 万字符，全译一遍占免费额度不到 10%——**实际支出为 0**。
CI 需要一对**只授 `alimt:TranslateGeneral` 的 RAM AK**（不要用主账号 AK），
存仓库 secret `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET`；
没配就整个跳过补译，`merge` 不受影响。

**漂移怎么判**：英文文件头有一条 `<!-- translation-source-hash: … -->`，内容是中文原文的摘要。
`--check` 拿它对；对不上即"英文落后"。当前还有 14 页未译，故该检查在
`.github/workflows/translate.yml` 里先设 `continue-on-error`——**译文补齐后删掉那一行即成门禁**。

动配置之前先知道两条构建口径：

- **`fallback_to_default` 会把未译页渲染出第二份**，故生成页里的每个标识都有两个 URL。
  `mkdocs-autorefs` 默认逐个告警（实测 89 条），`--strict` 下即失败；
  `mkdocs.yml` 里已开 `resolve_closest: true`——它按"离当前页最近"选 URL，告警随之消失。
- **语言选择器要整页跳转**：`navigation.instant` 与它不兼容，故已撤掉。
