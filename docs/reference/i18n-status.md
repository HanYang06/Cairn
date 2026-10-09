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

> **20 页中文页现在都有英文**（2026-10-10）。其中 6 页——本页与首页、向导三页、贡献页——
> 是机翻接线**之前手写**的：文件头没有摘要行，生成器**默认不动**它们（要纳入漂移追踪得跑
> `--stamp`）。其余 14 页由 CI 的机翻产出，头部带 `translation-source-hash`，故"中文改了、
> 英文没跟上"会被 `--check` 拦下。

## 已译清单

| 页面 | 中文（事实源） | 英文 |
|---|---|---|
| `index` | ✅ | ✅（手写） |
| `guides/quickstart` | ✅ | ✅（手写） |
| `guides/development` | ✅ | ✅（手写） |
| `guides/conventions` | ✅ | ✅（手写） |
| `contributing` | ✅ | ✅（手写） |
| `reference/i18n-status` | ✅（本页） | ✅（手写） |
| `reference/glossary` | ✅ | ✅（机翻） |
| `reference/config` | ✅（生成页） | ✅（机翻） |
| `architecture/index` | ✅ | ✅（机翻） |
| `architecture/storage-design` | ✅ | ✅（机翻） |
| `architecture/block-model` | ✅ | ✅（机翻） |
| `architecture/py_core/config` | ✅ | ✅（机翻） |
| `architecture/py_core/storage/block-parts` | ✅ | ✅（机翻） |
| `architecture/py_core/storage/pack-format` | ✅ | ✅（机翻） |
| `architecture/py_core/storage/query-path` | ✅ | ✅（机翻） |
| `architecture/ui_design/ui-theme` | ✅ | ✅（机翻） |
| `roadmap/1.x` | ✅ | ✅（机翻） |
| `roadmap/index` | ✅ | ✅（机翻） |
| `api/index` | ✅ | ✅（机翻） |
| `api/core` | ✅ | ✅（机翻） |

架构、路线图与 API 三类原本排在最后（措辞还在动，先译等于写两遍）；2026-10-10 一并译完，
**这张表此后不该再有 `—`**：新加的页按下面"一页怎么译"走一遍即可。

`fallback_to_default` 仍然开着，但**当前没有页面用到它**：未译的页在 `/en/` 下会由中文正文
渲染，而英文站现在不缺页面。新页先落中文的那段时间，`/en/` 下看到的是中文原文，
页面本身**不带标记**——那时以上表为准。

## 一页怎么译

1. 先写或先改**中文**页（`docs/path/page.md`）。**它是原文**，术语在那里定下。
2. 英文由 `scripts/translate.py` 用**机器翻译**产出为 `docs/path/page.en.md`
   （阿里云机器翻译通用版，`TranslateGeneral`；**签名与请求形状都照官方 SDK 抄**，不引 SDK：
   `POST` + 表单 body——正文不进 URL，签名本身按 RFC3986 编一次）。四条硬约束写在脚本里：
   - **只译正文**：围栏代码块整块保留，行内代码、链接、图片与裸 URL 先摘成占位符再放回
     （一译就断链、坏锚点）；表格分隔行不动；**只剩占位符与标点的那一行不送**——
     送了会被模型吐成 `?`，许可注释头就是这么坏过一轮的；
   - **增量译，不从头来**：每次只处理"**缺英文页**"或"**英文页落后**"的那些页，
     已一致的页**一个字符都不送**。故译文一旦落库，后续运行只花增量；
   - **并发送译**（默认 8 路，`--jobs` 可调）：一次往返约 1.1 秒，串行时 20 页要十几分钟，
     8 路降到两三分钟；
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
uv run python scripts/translate.py --report    # 报账：与 --check 同判据，但不判失败
uv run python scripts/translate.py             # 译"缺失或落后"的页
uv run python scripts/translate.py --stamp     # 只给手写英文页补摘要行（不重译）
uv run python scripts/translate.py --force     # 全部重译（连已一致的）
uv run python scripts/translate.py --probe     # 端点自检：只送两个字符，验凭证 / 签名 / 端点
```

**额度与设置**：机器翻译通用版对**主账号每月 100 万字符**免费，超出 50 元/百万字符。
本站中文原文约 9.5 万字符，全译一遍占免费额度不到 10%——**实际支出为 0**。
CI 需要一对**只授 `alimt:TranslateGeneral` 的 RAM AK**（不要用主账号 AK），
存仓库 secret `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET`；
没配就整个跳过补译，`merge` 不受影响。

**漂移怎么判**：英文文件头有一条 `<!-- translation-source-hash: … -->`，内容是中文原文的摘要。
`--check` 拿它对；对不上即"英文落后"。**它现在就是 `drift` job 里的真门禁**（2026-10-10
20 页译完后从 `--report` 换回默认）——手写的那 6 页没有摘要行，不参与判定。
**不要改用 `continue-on-error`**：写在 step 上与 job 级**都不改 job 结论**，实测两次仍报失败。

**端点自检**：`--probe` 只送两个字符，一次说清"凭证对不对、签名认不认、端点通不通"。它跑在两处——
`translate` job 里（花额度之前先自检），以及 PR 上的 `probe` job。后者限**同仓库分支**，
fork 的 PR 事件拿不到 secret。**为什么单拉一个 job**：`translate` 在 PR 上被 `if` 跳过
（它要建分支、开 PR，PR 上不该有第二个写者），若探针只住在它里面，"请求装配改对了没有"
在分支上就永远没有答案，只能等合并后在主干上第一次真跑——红过两次都是这么来的。

**两处触发，各管一段**（免得同一棵树扫两遍）：`drift` 与 `probe` **只在 PR 上跑**，
它们是"合并前看得见"的判据；`push` 到 `main` 只跑**写者**（补译 → 开 PR），因为它要改版本库。
主干那次的"还差几页"由写者自己的日志给，故不必再扫一遍。改工作流文件本身也不触发主干补译
（`push` 的 `paths` 不含它；PR 那侧含，好让改动在合并前被跑到）。

**合并前怎么验整条路**：`workflow_dispatch` 带 `dry=true` 时真调接口把整批译一遍，但**不提交、
不开 PR**——写者只在主干 push 上跑，故这是合并前唯一能真跑补译的场合。

动配置之前先知道两条构建口径：

- **`fallback_to_default` 会把未译页渲染出第二份**，故生成页里的每个标识都有两个 URL。
  `mkdocs-autorefs` 默认逐个告警（实测 89 条），`--strict` 下即失败；
  `mkdocs.yml` 里已开 `resolve_closest: true`——它按"离当前页最近"选 URL，告警随之消失。
- **语言选择器要整页跳转**：`navigation.instant` 与它不兼容，故已撤掉。
