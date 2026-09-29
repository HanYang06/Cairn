<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 决策

> 2026-09-16 存储层重写：早期「加密对象池 / 双源 / 结构库半加密 / 多空间 / manifest 版本链」
> 相关决策**全部作废**（已从本表移除）。以代码与 `docs/architecture/*.md` 为准。

## 书面语（2026-09-26 定 + 全仓已落，门禁已阻断）

- 已定 · **所有文档一律非口语化**（作者口径）：文档、注释、docstring、commit message、
  Issue / PR 描述、规则与记忆，**进入仓库的文本必须是技术文档语体**；日常讨论不受此限。
- 已定 · **三类文体各有基准**：规格 / 契约（`docs/architecture/`）= 定义式陈述；
  操作说明（向导 / README / 贡献）= 步骤与判据；工作备忘（rules / memory）= 紧凑条目 + 理由。
  三者都不用第二人称、语气词、比喻、感叹号。
- 已定 · **不靠自觉，靠工具**（作者明确表示无法自行做口语检测）：`tools/prose.py` **词典驱动**，
  `_LEXICON` 即标准本体；规则文件 `rules/references/prose.md` **只写判据，不复述禁用词**
  （复述会让规则文件自身被命中）。加词只收**歧义为零**的标记。
- 已定 · **豁免只能是行内且必须显式**：标记 `prose-ignore`，仅供"说明禁用形式本身"的行使用；
  **不提供文件级豁免**，避免整篇逃逸。
- 已定 · **门禁是阻断式，且本地与 CI 同口径**：pre-commit 只查本次提交的文件，CI 查全仓。
  先经一段**报告模式**（`--report`：命中不阻断、工具自身异常仍然失败）过渡，全仓清零后转阻断——
  两段式的用意是"先看得见，再卡得住"。
- 已定 · **位置也参与判据**：行首三叹号是 MkDocs admonition 语法，不能当"重复感叹号"报；
  故词典条目带 `not_at_line_start`。规则要能区分"写法本身"与"写法出现的位置"。
- 已定 · **为什么不只是措辞问题**：口语化会把写作时的情境一并带进文档，读者无法区分
  「哪句是规定」与「哪句是当时的想法」；同时使文档与代码的距离被语气掩盖。
- 已定 · **报告模式有个坑（已实测）**：它会把**新引入**的命中一起藏起来——报告模式期间整改代码
  自己写下的口语，只有翻全量输出才看得见；故清零后立即转阻断，不留"长期报告"状态。

## 内核短 API 的错误口径（2026-09-26 定 + 已落）

- 已定 · **失败必须抛出**：引擎把机制性失败记进 `Step.error`（设计如此），但 `Core.put` / `drop` /
  `call` 不得因此把失败当成功返回——落盘失败被吞掉，调用方读到的是"存好了"，属**静默数据丢失**。
  抛出的是**原异常**（不包新类型），调用方按类型捕获仍然有效。
- 已定 · **`call` 不得用 `None` 兼表两种语义**：方法正常返回 `None` 与"动作根本没执行"必须可分。
- 已定 · **`role()` 只返回实例**：类型表（`Core.type_of`）里存的是类，混进同一条返回路径会让调用方
  拿到类却按实例使用；未登记一律返回 `None`，由调用方显式创建。

## 文档（2026-09-26 定 + 已落）

- 已定 · **文档分两条线，不许合并**：**手写事实源**（`docs/**/*.md` + `README.md` + `AGENTS.md` +
  `src/**` 的 docstring，跟代码一起评审）与 **自动生成**（配置参考页 + `docs/api/` 的 API 参考 + `site/`）。
  **API 说明一律不手写**——手写的那份必然过期、与代码不符。生成走 griffe AST 解析（不执行代码）。
- 已定 · **生成的第一判据：能算的就不写、能查的就不写**（2026-09-26 补，作者质疑"生成是零"后立）：
  只要内容**已存在于代码 / 配置声明 / schema**，就该**投影**而不是抄。据此已落两件——
  ① **配置参考页** `docs/reference/config.md` **整页由 `tools/docgen.py` 生成**
  （源 = `schema/settings.json`，即配置引擎的生成物；含 SPDX 头与「勿手改」声明，正文零手写），
  **入库** + `--check` 防漂移；② **docstring 覆盖报告**（AST 统计，暴露"没写 docstring 的公共成员
  会从 API 页静默消失"这个此前不可见的事实）。
  **"生成"不包括 API 参考里那些 docstring**——那是人写在代码里的，工具只做搬运。
- 已定 · **生成物入库 vs 不入库，看它是不是给人读的**：`site/`（整站）不入库；
  给人读的**生成页入库**（`docs/reference/config.md`），好在 GitHub 上直接读、也能用 `--check` 比对。
- 已定 · **能用生成文件解决就别上 MkDocs 钩子**：钩子放在 `docs/` 下会被静默忽略
  （`docs/` 被当包目录，与导入撞名）；生成文件 + 防漂移门禁更好验证。
- 已定 · **工具链 = MkDocs + Material + mkdocstrings**（不用 Sphinx）：Material 中文支持好、
  Markdown 即源码（现有 `docs/` 零迁移）、API 抽取与 docstring 风格（google）天然对齐；
  **许可干净**：`mkdocs-material` MIT、`mkdocstrings`/Griffe ISC，均为**构建期依赖**、不进运行期 / 不进 wheel。
- 已定 · **生成物不入库（`site/`）**：`site/` 进 `.gitignore`（`REUSE.toml` 兜底声明）。
  事实源永远是 `docs/**`，站点只是它的一个投影——**不存在两份文档打架**。
- 已定 · **`nav` 即文档清单**：新页面必须在 `mkdocs.yml` 的 `nav` 登记；未登记页会被构建但隐身，
  `--strict` 不报错（这条靠自觉，写进 `rules/references/docs.md`）。
- 已定 · **`README.md` 只做稳定门面**：入口 + 定位 + 最短命令，**不复制**会长大的「现状 / 进度」
  （两处必然分叉；本任务就是来修这个债的）。细节一律链接到 `docs/`。
- 已定 · **权威顺序写进文档**：`代码 > docs/architecture/<具体篇> > <总纲篇> > 记忆 / 其它`；
  每篇标状态（草案 / 现行 / 已完成），看到「预留 / 草案 / 待定」就当它不存在。
- 已定 · **门禁口径 = `mkdocs build --strict`**：坏链接 / 缺页面 / 未知配置即失败，进 CI。
- 已定 · **发布 = GitHub Pages**（作者要现在就配）：`.github/workflows/docs.yml`，
  `main` 的文档变更 → strict 构建 → Pages；**PR 只做构建门禁、不发布**。域名（自定义域）暂不需要。
  一次性人工步骤：仓库 Settings → Pages → Source 选 **GitHub Actions**。
- 已定 · **许可澄清（记一笔免得再问）**：MIT / ISC / BSD / Apache-2.0 是**同一档宽松许可**，
  用它们**没有**任何"被限制"的问题，也**不影响商用**；红线只针对 **GPL / AGPL**（传染）。
  真正要躲的是**禁止商用**类许可（CC-BY-NC / PolyForm NC）。故"2026 年了要用新的、稳定的、强大的工具"
  与许可红线**不冲突**——只要不碰 GPL/AGPL。
- 已定 · **一个仓库只有一个 Pages 发布者**（2026-09-26）：本站 = `docs.yml`（MkDocs）。
  **不用 GitHub 引导生成的 `jekyll-gh-pages.yml`**：它从仓库根构建、产物是整个仓库当静态站，
  与 `docs.yml` 抢同一环境且互不取消 → 站点来回跳还不报错；功能上也不互补（无导航 / 搜索 / API 参考）。
  若 GitHub 再生成它，直接删。
- 已定 · **`jieba` 不引**（中文搜索分词）：Material 的 zh 搜索**可选**依赖，但本机 `uv sync` 构 sdist 失败；
  Material 对 CJK 有字符级回退，搜索可用。要用得上时再补（记得它虽是 MIT，也仍属构建期依赖）。

## 配置（2026-09-26 定，第一片已落）

- 已定 · **配置是个引擎，不是"统一参数面"**：它只管"配置"这件事（声明、投影、取值、校验）。
  `ui_tools/core/conf.py` 的 `Conf`（Facet 的 `theme` / `attr` 门面）是另一回事，两者不合并。
- 已定 · **各管各的**：谁要用配置，谁在自己包里声明（`src/core/storage/conf.py` 声明存储参数），
  配置端**只负责展开与取值，不替别人管**。
- 已定 · **声明即事实，两个投影落盘**：`Cfg` 写在声明模块的类体里，绑上即报到，引擎展开出
  **两套一一对应**的文件——`config/<包树>/<文件>.<CONFIG_FILE_TYPE>`（值）与
  `schema/<包树>/<文件>.json`（词表，固定 json），`<包树>` 与 `src/<包树>` 同构。
  注册是唯一真源；文件删了能按声明重展开。
- 已定 · **默认值的语义**：传了值 → 两侧都出现（值文件带数值）；没传值 → 只有词表出现，
  值丢了即报错（补不了）。`empty_ok=True`（即 `default=True`）是**增强写法**：
  哪怕值是空的（`""` / `None` / `[]`）也按默认处理。
- 已定 · **hub 是命名空间，不是装饰**：生成物落 `config/<hub>/…`、`schema/<hub>/…`，总词表
  `schema/<hub>.json`；默认 hub = `settings`（**不叫 `config`**，否则又成 `config/config` 那种迷糊）。
  生成物与手写口各用一个 hub，**结构上就不撞**，再加一道**重名检查**兜底（见下）。
- 已定 · **重名检查（不覆盖别人的文件）**：目标路径已存在且认不出是本引擎的投影即**拒写**——
  ① 有 `$schema` 但指向别处 → `ConfigConflictError`；② 无 `$schema` 且找不到本引擎登记的键 → 同；
  ③ 读不成 JSON / 根不是对象 → `ConfigFileError`。工具会逐条列出来让人搬迁或换 hub。
  （2026-09-26 修正：早先"直接把 hub 层砍掉"是偷懒——该用检查兜住，不是删结构。）
- 已定 · **取值三条**：key 在、值空 → **报错**（不猜、不自动修）；key 丢、有默认值 → **补回来**；
  key 丢、没默认值 → 报错。**用户改过的值永不覆写**（补只补缺失的键）。
- 已定 · **命名雷区**（踩过）：① 包名与包内同名子模块会互相覆盖 → 内核自己的声明模块叫
  `params.py` 而不是 `conf.py`；② `core/__init__.py` 里 `from .conf import conf` 会把实例绑到
  `core` 上，遮住 `core.conf` 子模块 → **父包里不转出与子模块同名的对象**。
- 已定 · **格式版本号不进配置**：`CATALOG_VERSION` / `BLOCK_VERSION` 这类改了会坏库的，留在实现处。
- 已定 · **"接线"的口径**：声明是唯一事实来源——实现里**不抄第二份默认值**（`BucketConfig` 造一次就向
  引擎要一次）；已建好的库把自己那份值存下来（重开读回），**老库不被新默认值偷偷改掉**。
  环境旋钮（`CAIRN_VAULT` / `CAIRN_THEME_DIR` / `CAIRN_SHAPES`）是开发 / 部署入口，**暂不进配置**。
- 已定 · **不做**（曾推演、已否）：生成物镜像 / 代理 / 墓碑保活 / 自动扫全项目 / 统一入口 + 覆写两层。
- 已定 · **文件引用写同层级的相对引用名**（2026-09-28 定 + 已落）：声明了 `file_type` 的项，
  值文件里那一行是**相对该值文件自己所在目录**的引用名，默认即同层级的 `<字段名>.<类型>`
  （`"storage.db.tables": "tables.yaml"`）。理由：仓内全路径太长、且与绝对路径只差一步，
  而绝对路径搬一次仓就断；引用名像 `import`，整棵配置树搬到哪里都成立。
  **只收相对引用**；那一行是**事实而非装饰**——改成别的相对引用即换文件，补缺不改回默认；
  词表侧按**字符串**出（值确实是字符串），被引用文件类型记在 `x-cairn-file-type`。
- 待定 · 手写口（个人覆写 / 多 hub 合并）的启用时机；`jsonschema` 校验路径。

## 存储重设计（2026-09-28 定；**已落地并接进内核**）

> 设计篇 = `docs/architecture/storage-design.md`（**该篇是 L0 的唯一事实来源**）。
> 本节只记"已定的关键判断 + 为什么"，细则不在这里复述。旧层已退役。
>
> 落地时撞出的三处更正（都在本节与设计篇里写明了）：① **指针在载荷里**，不在 ID 里
> （记录层自校验优先，§3.2.1）；② **按索引列举**，不按顺扫（同一身份的旧副本会重复出现，
> 而索引那一行才代表"对象现在在哪一份"）；③ **告警不是失败**（库里多出的列 / 表不拦开库，
> 否则建过一张领域表就打不开库）。

- 已定 · **从零重设计，不背兼容包袱**：无发布、无真实用户库（`git tag` 空、`version = 0.0.1`、
  vault 外无库），故旧落盘格式、旧目录、旧 ID 一律不必兼容。
- 已定 · **四层**：块 / 载体（桶）/ 多桶 / 索引库；**索引库是桶的组件**，不是与桶并列的一层。
- 已定 · **ID 是身份证，不是裸字符串**：`Id` 对象含两套凭证（`value_uuid` 分配形态、`value_hash` 摘要形态）、
  名字（由所在容器得出）、`issued`（ID 自身签发时刻）、`issuer` 与位置段（含**预留的网络字段**）。
  两套凭证**各有其用、并存不取**：比较用分配形态，去重用摘要形态。
  物理坐标**不进 ID 的落盘子集**。
- 已定 · **ID 是给 body 用的、块与 ID 绑死**：body 持有 ID；块记录携带的是指向该 ID 的凭证
  （取摘要形态）——**落在载荷的 `body_addr` 里**（见本节开头的更正①）。
- 已定 · **块记录与内容记录是两种记录，故索引要两层定位**：记录表（`value_uuid` 主键，定位块记录本身）
  ＋ 内容表（`value_hash`，支持跨块共享同一份内容）。
- 已定 · **类型无界但只是继承层级，不是嵌套**；**类型标号不落盘**，类型由程序给，
  不认识的 ID 一律降级读回（扫描 / 重建 / 合并都靠它，一处抛错即断链）。
- 已定 · **落地盘面**：定长槽（槽长随载体、写在文件头）、记录自框定（总长在最前）、
  **不设封口目录**（顺扫即可重建；目录只是优化）。
- 已定 · **版本不属于存储**（归领域）；手工版本号（`BLOCK_VERSION` / 各域 `*_SCHEMA`）作废。
- 已定 · **表声明进配置**，源码内不得出现建表 SQL；只允许加、破坏性变更拒绝启动；
  建表只在开库 / 挂载，不在热路径。
- 已定 · **索引库的可重建是逐表性质**：内核态可扫载体重建；领域态含真源在库内的表，
  损坏即永久损失，**备份是必需能力**。
- 已定 · **并发 = 短命桶 + 合并回主桶**（方向已定、未实现）；同 ID 冲突按 `issued` 裁决。
- 已定 · **顺序：文档 → 类型与异常 → 字段 → 作者审字段 → 业务逻辑**；不写工作树、分支开发。
- 已定 · **多桶的价值是确定性路径查询**（2026-09-28，作者口述）：物理多桶、引擎视角一块盘，
  查询就是"先查桶、再按槽区间读块"——两跳都是查表。故**桶上名称或 ID 没有区别**：
  桶名就是桶的目录名，取人话（`main`）或取 ID 形态都对查询无影响；
  桶本身**不持有 ID**（ID 是 body 的身份证，桶是容器，§3.2.1），它的标识就是它的名字。
- 已定 · **桶是无状态的一层**（2026-09-28 落）：桶目录即存在证明（判据＝带 `packs/` 的直接子目录），
  索引库里的桶表只是**登记**；槽长随载体走（文件头自描述），封口线每次写入按配置判，
  故桶不存自己那份配置；读路径缺目录即报错，不悄悄建空桶顶上。
- 已定 · **封口不留标记**（2026-09-28 落）：没有封印字节、也没有封口文件，
  "已封口"就是"该载体达到封口线"，故封口是**策略判断**而非落盘状态；
  **活跃载体＝有空间的最满者**（写入纪律是"写到满才换"，故该判据不依赖时间戳与名字顺序；
  封口线调大后仍只有唯一答案）。单条记录大于封口线时照样完整写入（否则大记录永远写不进去）。
- 已定 · **载体名取随机串**（无语义、无顺序号）：序号名在压实之后会被重用，
  而重用的名字会让**过期的索引行指向另一个文件**；随机名只会指向不存在的文件，坏得看得见。
- 已定 · **重建分两种口径**（2026-09-28 落）：档一重建＝**只补缺行**（已有行不动）——
  因为 `kind` 与落盘时刻不在记录头里，清空重扫会抹掉类型信息；权威重建待 ID 专项裁定。
- 已定 · **巡检只报告、处置只补不删**（2026-09-28 落）：`patrol()` 把索引与真源两头对齐，
  发现按"可否由重建修复"分类；`repair()` 只动可修复的那部分——内容没了、桶没了、载体坏了
  一律不碰（删行等于把"丢了东西"抹掉）。**坏点即停属于重建、不属于巡检**：
  重建拿半份结果不能当结果，巡检要接着看完。
- 已定 · **ID 管自身、载荷管指针**（2026-09-28 定，修正原 §3.2.1）：块记录的身份凭证
  `value_hash` **恒为该记录自身载荷的摘要**——记录层的自校验就这么要求（`Record.decode` 当场核对），
  故它无法同时承载 body 的摘要。原稿的"一格两用"（指向身份 ＋ 内容判重）作废：
  指向 body 的凭证落在**块记录的载荷**里（`body_addr`），去重与反查仍走 `value_hash` 索引
  （内容记录的身份就是该地址）。指针在载荷里**不影响可重建**：顺扫读出载荷即得指针。
- 已定 · **块面 = 两条记录**（2026-09-28 落）：内容记录（载荷即编码后的 body，身份按内容签发）
  ＋ 块记录（载荷是属性与 `body_addr`，身份是块自己的）；读回两条一拼。
  判据落在载荷格式上，故档一重建补回的块行照样认得出是块（类型为空也能列举）。
- 未来项 · **合并与短命桶**（2026-09-28，作者：无所谓，记下即可，短期不做）：
  并发承接 + 合并回主桶 + 销毁；"合并期桶归属改写"随之推后，取舍表在设计篇 §7。

## 存储（2026-09-16 重写）

> ⚠️ **2026-09-28 起由「## 存储重设计」与 `docs/architecture/storage-design.md` 取代**。
> 下列条目中凡与二者冲突者（目录为唯一真源、块字段含 `checksum` 作 `id`、目录 DDL、分片口径）**不再有效**；
> 保留本小节仅作历史记录，待旧代码清理后删除。

- 已定 · **桶 + 块**是唯一内核：`Bucket`（载体/文件系统管理类）+ `Block`（存储单元）；
  其余一切（note/asset/project/画板/索引/变更）都是块或其属性。
- 已定 · **本地不加密**（明文落盘）；加密只用于传输/服务端。删除 crypto / manifest / space / 分块池。
- 已定 · 块字段：`id`（稳定 OID，锁死）/ `checksum`（内容哈希，十六进制串）/ `type` / `body` /
  `attrs` / `config` / `author` / `size` / `created` / `updated`。哈希一律是字符串。
- 已定 · 去重在**领域层**（note 只与 note、project 只与 project 比 checksum）；分片块不去重。
- 已定 · 分片由块自带（`Bucket.put_content`）：大内容 = 分片 + 索引块。
- 已定 · 目录（catalog DB）是块位置的唯一真源；pack 只追加、顺序命名、写满封口。

## 领域（2026-09-16）

- 已定 · 领域结构**直接继承 `Block`**（无中间层）；通用读写（save/load/list/oid/info）在 `Block`。
- 已定 · `Attr(item=)` 让列表字段类型化：存储是紧凑数据，取出来是类型化对象。
- 已定 · `composition` 并入 note（移除独立对象）。
- 已定 · **组（`cairn.group`）**：独立块；域 ID **`gid`** 与块 `oid` 分开（不改 `Block`）；
  `group: list[str]` 有序子项（组存 gid、其余存 oid，可无限嵌套）；成员**两套都存**
  （列表存结构顺序 + `relations` 存 `contains` 反查）；`lock` 锁编辑；`owner` / `member` / `key`
  为社区「有限编辑组」预埋（`User` 系统落地前用字符串）。
- 已定 · 关系是**一等 DB 行**（`relations` 表）：`derived-from` / `references` / `contains` 等多类型，
  用于引用拓扑；`provenance` 查表。
- 已定 · note 正文 = `list`（文字段 + 占位符）；样式等长对齐；画板/多媒体用
  `{"canvas": n}` / `{"access": n}` 占位。
- 已定 · 画板 = **数值序列**：`Canvas{graphics, links}`、`Graphic`（预制编号 + 中心点 + 缩放/旋转 +
  点路径 + `Paint`）；连线只存图形下标 + 线型，走线派生。
- 已定 · 预制图形**外置**：`config/shapes.json` + 生成器；形状是生成器概念，点是渲染概念。
- 已定 · 标签用 dict（`{键: 值}`）；作者 = `author`（原作者）+ `authors`（有序署名）。
- 已定 · 笔记版本 = **增量 diff 落 DB**（`versions` 表），保留窗 30 天、惰性压实；块不管版本。
  （2026-09-24 现状：该实现已随内核重建**移除**，`versions` 表当前无人写；待 Q7 裁定后装回。）
- 已定 · `Asset` 入库先转码到统一编码（草案；图片/音频走不传染库，视频暂不转码）。

## 笔记编辑模型 / 版本引擎（2026-09-17，M0）

- 已定 · 正文 `body = list[{"id","v"}]`（**一元素 = 一行/一块**），元素带稳定行 id；`v` 为
  文字或嵌入占位（`{"canvas":n}` / `{"access":n}`）。行序列保序用 list（canonical CBOR 会排序 map key，dict 不能保序）。
- 已定 · 样式是**非对称覆盖层** `style = {行id: [ {区间(tuple): Style} ]}`；行内区间可叠加，
  后层压前层；规范化为不重叠、有序、去默认。行内加粗不拆 body。
- 已定 · 行 id 用 ULID（`Oid`），生成即锁死；行增删/重排不动样式，**无下标漂移**。
- 已定 · 内容地址 **cID（checksum）剥离行 id**：同文同样式即同签名 → 纯复制/同文可去重；
  改一字即不同。id 不参与内容计算。
  （2026-09-22 修正：**去重键 `body_hash` 改为与落盘负载一致、含行 id**——原用法会让「同文不同行 id」
  的笔记命中同一内容行、读回静默串行 id；剥离行 id 的 `body.hash` 仍用于创作签名 / 版本 `digest`。
  代价：仅行 id 不同的同文笔记不再去重。见 `docs/architecture/storage.md` §4。）
- 已定 · 版本用**通用引擎 `VersionStore`**（`core/store/version.py`，block 亲和）：版本 id =
  `blake3(canonical({prev, at, sig}))`，`prev` 单亲链；顺序从 head 沿 prev 走，不靠时间/序号；
  第一版记根节点（空补丁）。域提供 `Codec`（digest/diff/apply），笔记 Codec 在 `note/versions.py`。
- 已定 · diff 是**反向补丁**（新→旧），按行 id：`PUT`（载荷=旧值，回放写回）/`DROP`（该行为新版新增）/
  `@order`（有行增删 / 重排即出现，回放时以它为准）；未变更行不入补丁。载荷必须是旧值（当前版本只在块里，回放只能倒推）。
- 已定 · 哲学「**笔记残页**」：diff 脱离当前块上下文即失效；压实=永久遗忘；传输必须带 base；
  需要 `fold` 把链折成新版本（尚未实现）。
- 已定 · ID：`id`（块身份，str）+ `oid`（同值，Oid 对象）即可；**不再另立 nid/pid**（已回退）。
- 已定 · 长行不设内核上限，交给 UI：超阈值关自动换行、逼硬回车产生新行。
- 已定 · **body 内容池在桶里**：`checksum = body_hash`（只算 body：文字+样式+占位，剥离行 id），
  `contents(body_hash → 位置)` 即去重池，查找 O(1)；**attrs 随块行存、不参与去重**
  （标题/标签/签名/时间不同不影响同正文去重）。body 与 attrs 分家存储。
- 已定 · **段落 = 行**：**1 个硬行就是 1 段**，不设独立段落实体；段级属性放行元素 `p`，
  字级仍走行内区间 `style`。超长行（等效中文 > 300）由 UI 关软换行、转横向滚动逼硬回车，**不自动拆行**。
- 已定 · **工具 = 基类 + 参数化实例**（`feature/note/tools.py`）；**分组 / 位置是数据**
  （`PRESET_LAYOUT`，将来可用户自定义）。工具栏两行（编辑型字级 / 段级）、纯图标 + 提示、溢出**向下抽屉**。
- 已定 · **工具四分类**（2026-09-17）：`ToolCategory` = 添加 / 编辑 / 命令 / 查询；分类是工具元数据
  （抽屉内分组），两行预设只放编辑型，其余自定义时随便摆。**编辑型 / 添加型**改 note、元数据在
  `feature/note/tools.py`；**命令型 / 查询型**属应用与界面（UI 待重建，归 `ui_tools` / App）。
- 已定 · **`Tool.state` 只读三态**（2026-09-17）：`run` 写、`state` 读；`state` 返回 `True` 生效 /
  `False` 未生效 / `None` 混合，供工具栏高亮；四类里只有**编辑型**有可读状态。未实现工具
  `available=False`（UI 置灰、不执行），不假装已存在。
- 已定 · **保存与版本分离**：自动保存只落盘（`Note.persist`）；版本检查点仅在**非连续编辑边界**产生
  （空闲超时默认 5 分钟 / 切换笔记 / `Ctrl+S` / 退出），避免逐次保存堆出大量微小版本。
- 已定 · **`Body` 是容器基类**（`core/store/block.py`）：无 ID、依存于块；自带状态字段 `hash`
  （对 `content()` 求摘要，**只含内容字段**，排除自身状态/时间戳）。内容一变就 `refresh()` 重算并缓存。
  旧描述符改名 **`BodyField`**（裸 body 用 `BodyField()`，结构化用 `BodyField(prototype=...)` 每实例一份）。
- 已定 · **`NoteBody(Body)`**：字段 `text`（行序列）+ `style`（行内样式）；`content()` 剥离行 id，
  故 `body.hash` 只反映文字+样式 → 同文同样式同哈希。`Note.body: NoteBody = NoteBody()`（类型自证，无需标记，
  `Block.__init_subclass__` 自动包成 `BodyField`）；`note.style` 是 `body.style` 的代理。`checksum = body.hash`。
- 已定 · **签名是复合结构（一组字段），不是一段串**：`Signature{alg, author, created, subject, prev, value}`；
  自包含、自校验（改任一字段 value 对不上）。创作签名创建即锁死、`subject` 指向创建时 body_hash（原始结构可找回）；
  变更签名（非原作者、prev 链）为多作者预留。当前 `alg="b3"` 哈希链，日后换 `ed25519` 不破格式。
- 已定 · 字段类型化：写法为 **`field: Attr[T] = 默认值`**（注解即类型、右边即值；`Block.__init_subclass__`
  自动包成描述符）。mypy 靠自研插件 `tools/mypy_plugin.py`（base class hook）把 `Attr[T]` 字段的可见类型
  改写成 `T`，**无需 ignore**；显式描述符字段（`coerce`/`item`）写**裸 `Attr`**，插件不动。
  `title/tags/authors` 属业务字段，已从 `Block` 挪到 Note/Project/Asset（`Block` 只留硬件字段）。
- 已定 · **`Attr` = 属性字段，`Data` = 数据字段**（两者同机制、同存储）。`title/tags/signature` 等描述性
  元数据用 `Attr`；承载数据的 `canvas/access` 用 `Data`（避免"属性"用词错位）。位置不变、仍在块内。
- 已定 · **`Canvas` 升格为块**（`cairn.canvas`，`feature/canvas.py`）：`Canvas(Block)` + `CanvasBody(Body)`
  （`mode` diagram/sketch + 图形 + 连线）；全局内容寻址、去重。note 的 `canvas: list[str]` 存 canvas oid。
- 已定 · **不设 `Access` 类**：外联资源就是 `Asset`（Block）；note 的 `access: list[str]` 存 asset oid（全局去重）。
- 已定 · **数据字段免标记**：裸容器注解自证类型，自动成 `Data` 字段（每实例一份）——
  `access: list[str] = []`、`canvas: list[Canvas] = Canvas.container(list)`。属性仍需 `Attr[T]` 标记。
  `encrypt/shareable` 等硬件配置位未加。

## 工程 / 产品

- 2026-09-14 · 已定 · skill 放 `.agents/skills/`；根 `AGENTS.md` 只做索引；`rules`=约束、`memory`=现状。
- 2026-09-14 · 已定 · 布局契约：三栏 SplitView，属性栏默认收起；列表交互照 VS Code、不做过渡动画。
- 2026-09-14 · 已定 · 删除先入回收站；**版本只记内容变化**（元数据不产生历史）。
- 2026-09-14 · 已定 · 分发：源码与 Windows 桌面 P0（PyInstaller onedir + Inno）；macOS 暂缓。
- 2026-09-16 · 已定 · UI：精简、自然；色盘照 GitHub，圆角与阴影照苹果；中英统一等宽字体
  （链条首为「更纱黑体 / Sarasa Mono SC」）。
- 2026-09-16 · 已定 · 只引不传染许可（MIT/BSD/Apache）的依赖；GPL/AGPL 禁用。
- 2026-09-17 · 已定 · **质量口径 =「企业级-ε」**（企业级略降半档）：mypy strict（`src`+`tools`）、
  ruff `select=ALL` + 逐条有理由的 ignore、`ruff format` 强制、warning 零容忍、覆盖率行+分支 ≥80%。
  中文项目现实豁免：中文标点（RUF001-003/D415）、方法级 docstring（D102/105/107）、领域词汇 id/type/hash（A002/A003）。
  标准见 `rules/references/quality.md`，配置事实源在 `pyproject.toml`。
- 2026-09-17 · 已定 · **代码是唯一事实，文档随代码回写**；旧概念（manifest / space / chunk / 基板 substrate /
  keyed CID）不再复活，架构文档与 `README.md` / `AGENTS.md` 已同步。
- 2026-09-19 · 已定 · **导入面必须统一、直观**：同一件事的代码收在同一个目录 / 包下、从一处可导入，
  不许散落。判据 =「外部开发者懒得研究内部，散乱就导入不了，只会骂作者」。布包时按"使用者视角"归拢。
- 2026-09-21 · 已定 · **AI 评审用 `alibaba/open-code-review`（OCR，Apache-2.0）**：确定性工程 + Agent
  混合架构，只作开发 / CI 工具，不进运行期依赖；本地走 `ocr` CLI + OpenCode 插件，CI 走
  `alibaba/open-code-review` composite action，模型 DeepSeek `deepseek-flash`，key 走环境变量
  `OCR_LLM_TOKEN`（本地）/ 仓库 secret（CI）。许可与 GPL/AGPL 红线不冲突。
- 2026-09-24 · 已定 · **SPDX 头不靠手抄**（三层）：① **写** = `tools/spdx.py --fix`（自研、纯标准库、
  mypy strict），已挂 pre-commit；② **查** = 同工具 `--check`（缺头 / 年份错 / `SKILL.md` 少 `license:`
  都非零退出，并报「既装不下头又没在清单里声明」的文件）；③ **兜底** = 根 `REUSE.toml` 集中声明
  图片 / JSON / 锁文件 / `LICENSE` / `NOTICE` / 第三方 vendored 的许可。原有 ruff `CPY001`
  （`flake8-copyright.notice-rgx`）继续管 `.py` 的版权行。
  **不引入 `reuse` CLI**：`fsfe/reuse-tool` 本体是 GPL-3.0-or-later，撞红线；只采用它定义的
  `REUSE.toml` **数据格式**，读写自己实现。
- 2026-09-25 · 已定 · **编辑器层只做便利、不做约定**：PyCharm 的 Copyright profile（`.idea/copyright/*.xml`
  + on-save 更新）与 VS Code 的片段 / 任务 / 模板扩展都属**个人效率件**，换编辑器即失效；约定一律留在
  仓库层（`.editorconfig` + pre-commit 钩子 + CI + `REUSE.toml`），这样任何人 / 任何 IDE / AI agent
  都不会漏。VS Code 侧选 `TrevorNesbitt.smart-file-templates`（**MIT**）；同类
  `rioj7/vscode-file-templates` 仓库无 LICENSE（默认保留所有权利），**不选**。

## 目录结构（2026-09-19，重定；同日再调）

- 已定 · **取消 `cairn.` 前缀**：`src/` 下直接放顶层包；导入形如 `from core.storage import Bucket`。
- 已定 · **当前四层**：`core`（底座）/ `feature`（领域）/ `ui_tools`（界面工具箱）/ `app`（应用，按平台
  `win` / `linux`）；辅助 `core/conf`（配置 / 常量）。**删除** `src/conf`（并入 `core/conf`）、
  `src/net`、`src/server`、`src/ui`（→ `src/ui_tools`）。
- 已定 · 早期重命名：`core/store → core/storage`、`domains → feature`、`cairn/types` 并入 `core/types`。
- 已定 · `core` / `feature` / `ui_tools` / `app` 进 hatch wheel。

## UI 技术路线（2026-09-18，现行）

- 已定 · **Widgets 宿主 + QML 岛**：工作台外壳、列表/树、检查器、编辑器、菜单/对话框全部走
  QtWidgets（Python 对象组合）；QML 只保留给**画布 / 大规模关系图 / 特殊视觉**这类自包含「岛」。
- 已定 · **编辑器用 `QTextEdit` + `QTextDocument` + `QUndoStack`**：一条硬行 ≈ 一个 block，
  与笔记行模型同构；跨行选区、撤销/重做、IME、代码高亮由框架提供（QML 逐行 `TextEdit` 做不了）。
- 已定 · **判据三条**：① Qt 只支持 Widgets 里嵌 Quick，不支持 Quick 里嵌 Widgets；
  ② App 需要的动效类别（硬切/软切/渐变/滑移）Widgets 全覆盖，QML 的连续高频场景图收益与产品不符；
  ③ **实现语言须在负责人射程内**——组件库用 Python，负责人可参与设计与维护（QML 做不到）。
- 已定 · **命名分层**：`App`（QObject 组合根：Session/facade/命令表）+ `MainWindow`（QMainWindow）
  + `Component` / `Panel` / `Page`（部件基类）。依赖显式注入，不用全局单例。
- 已定 · **QML 岛是哑视图**：输入类型化 VM、输出回调；不持应用状态、不碰 Vault、不反向耦合。
- 已定 · 组件建造四规则：**联动在控制器**（compound components，不控件互连）、
  **布局靠 `VBox/HBox/Grid/Split` 嵌套组合**（不新增原语）、**增长只在原子与页面**、
  **主题 = 点分配置 → QSS 编译 + 有限 Qt 侧增强**。细则见 `rules/references/ui-boundary.md` §6。

## UI 内核（2026-09-19，重定；设计总纲 `docs/architecture/ui-kernel.md`）

- 已定 · **两套内核**：数据内核（`core`/`feature`）升级调整；UI 内核（`ui/`）重新设计。
  **UI 内核 ≠ Qt**——它负责「对象 → 界面」的生成 / 编译 / 绑定 / 配置，Qt 只是实现材质。
- 已定 · **技术路线：QtWidgets 宿主 + QML 岛**（沿用 2026-09-18 三条判据）；画布 / 大关系图走 QML 岛。
- 已定 · **数据直通 = 内核预埋信号代理 + 投影 + 命令**：信号代理（现为 `core/events.py` 的
  `EventBus`）是 UI 与 feature 的统一变更源；UI 经 `投影(Session) → Bridge → Model` 消费，
  **不 import `feature`、不碰 `Vault`/`Bucket` 内部**；写回一律走命令。**单向数据流**。
- 已定 · **快捷创建 = 对象驱动生成**：由领域对象（Note/Project…）内省出 **UI 模板树**（可用初稿）+ 套通用架构默认行为；开发者只改细节。**特化优于通用**，不求外部框架式极致通用；自动生成只出模板，细节不猜、不假装已实现。
- 已定 · **事件绑定 = 声明 + 编译**：组件只发意图 → 命令；内核信号 → Session → Qt。**不做响应式框架 / reconciler / 双向绑定**。
- 已定 · **统一 Config = Theme（封闭词表，外观唯一真源）+ UiConf（开放词表，随组件生长）**；选择器 `widget.<类型>[:<状态>]`，**比 CSS 轻**（不做层叠 / 继承 / 优先级）。
- 已定 · **数据内核须配合补**：字段内省 API（现缺，类型信息只在 `Block.__init_subclass__` 内部消费）、
  字段 traits（纯数据展示语义）、`batch` 合并事件、`Vault` 死 API 收口。
- 已定 · **各司其职 = 领域契约**：领域对象除结构 / 事件外，另声明 UI 可消费的契约
  **`fields` / `actions` / `signals`**；UI 按契约绑定与生成。**契约是领域的事，渲染是 UI 的事**。
  契约**不得长在 `Block` 上**；字段描述符（`Attr`/`Data`）属存储机制，在内核边界内投影为中立
  `FieldSpec{名字,种类,traits}`，UI 只读 `FieldSpec`，不外泄 `Attr`/`Data`/`Block`。
- 已定 · **Bucket / Block 与 UI 正交**：`core.storage`（Bucket/Block）是存储实现，**UI 不 import、
  不复用、不感知**（UI 里出现 `bucket`/`block`/`body`/`attrs`/`checksum` 即失控）；判据=
  「新开发者要懂 UI 须先学 Bucket/Block」即失败。**已有架构测试**断言 `ui_tools` 不 import
  `feature` / `core.storage` / `core.vault`（`tests/test_architecture.py`）。
- 已定 · **实现归位**：`core/signal/`（Qt-free 通信主干，**已实现**）、`ui_tools/core/`（UI 内核，**已实现**）；
  `EventBus` 已并入 `core/signal`（不再单飞）。
- 已定 · **验收指标**：加领域字段 = 领域一处（+traits），UI **0~1 处**；加标准动作 = 契约一处。
  加字段仍要改 5 个 UI 文件 = 设计失败。
- 已定 · **代理是必然的（内核在变，UI 不变）**：内核随业务 / 数据变，UI 可不变，靠**代理**挡住。
  **两端各一代理**：数据侧 `core.signal.Signal`（包内核、稳定面 + 取实体操作入口）；UI 侧同构代理
  （对接 Qt 信号槽）。**`Bind` 把两个稳定面接起来**——绑定对象因此必然存在。`Signal` **不生成页面**
  （生成页面是 `Facet` 的事）。
- 已定 · **交付单元 = `Facet`**（原 `Page` 生成器含义弃用，`Page` 退为内层页面层）：一个域的整套
  UI 定义（布局 + 部件 + 绑定），由领域对象生成；`Facet(Note)` / `class NoteFacet(Facet)` 同树。
  交付：**直接交给 App（组合根）**，由 App 编译 / 挂载 / 接信号（定义被动，外部发起）。
  `Facet.__init__` **只声明两件事：属性配置 + 绑定**。
- 已定 · **绑定模型**：`bind = Bind(self)`（作用域 = Facet，随生命周期释放）；
  `bind.add(源, 目标)`：源为 UI 信号（**明确到信号**，如 `self.save_btn.clicked`），目标为
  领域 `Signal`（`self.note.favorite`）或本类方法（`self.on_clear`）——UI→内核 与 UI→UI 同写法；
  参数沿 source→target 传；**编译期校验**信号名 / 签名。Qt 物理事件与控件事件由 UI 侧代理
  **统一包成 `Signal`**，作者不碰 `QEvent`。
- 已定 · **总目标（唯一尺度）**：**更便捷、更快、更轻量、更少工作量**。
- 已定 · **`core/signal` = 现有 `EventBus` 升级，不重造**：分两层——**存储事件**（已有
  `ObjectPut`/`ObjectDeleted`）+ **语义信号**（各域声明"会喊哪些话 / 关心哪些话"，
  `emit(名字,数据)` / `subscribe(名字,处理)`）。域间**不 import、只认信号**；听了**重新读**当前状态
  （不缓存假设，解"邻居突变"）；通知非命令；处理器不可重入。`Signal(Note)` = 域的信号 / 动作句柄。
- 已定 · **`Facet` 自包含规则**：主题等内置属性**自带**；布局 / 部件**不自包含**——自己 import、选、
  配好（专属配置在对象自身）再放进去。**`set` = 设形态**（`layout.set(Grid)`）、
  **`add` = 加持有**（`layout.add((1,2),Editor)`），**语义不可混**。产物 = **对象本身直接交 App**
  （`Facet` / 包装对象；**不序列化、不加中间格式，是啥传啥**）。
- 已定 · **Config = JSON**：顶层 `token {…}`（全局外观）+ 具体配置（`note.<…> = 值` / `note.<…> {}`）；
  App 认识所有 `Facet` → **自动生成 JSON schema**（键自动列出、可校验）；**布局参数也在其中**
  （拖布局 = 改文件，不动代码）。
- 已定 · **QML 岛 = 组件化增强**（非完整 UI、非外壳）：画布 / 大关系图等**特定领域增强组件**，
  按普通原子处理——包一层 `QQuickWidget`，对外"配置进 / 信号出"，**接法同普通部件**。
- 已定 · **字段显示属性固定四词**：`label` / `group` / `display` / `editable`；**能按类型推的不写**，
  领域一并挂、UI 照做。
- 已定 · **多页面 = `Facet` 里的 `Page`**：`Page` = 单页（布局 + 部件 + 绑定），是导航目标；
  `Facet` 持多 `Page` 并声明怎么切（`tabs`/`stack`/主从，默认 `tabs`）；**单页域不显式写页**
  （`Facet` 即默认页）；宿主由 App 给、页面懒加载、切换触发 `on_enter`/`on_leave`。
- 已定 · **字段从领域对象分析而来、不写死**；`label`/`group`/`display`/`editable` 只是**可选显示提示槽位**，
  值随领域；**信号**告知"它现在有哪些字段"。
- 进行中 · 分阶段 M0 地基 → M1 外壳 → M2 生成 → M3 扩展；每阶段以 note 打穿闭环。
- 已定 · 本设计**预期与现有 UI 规则冲突**（`ui-boundary.md` / `ui-theme.md` / AGENTS 红线），
  届时以本方向为准定向改规则。

## 内核重构（2026-09-22，M0 封版；规格 = `docs/architecture/kernel-spec.md` v1.0）

- 已定 · **性质变更：由「存储核心 + 通知」改为「对象主干 + 事件对象」**。主轴是**对象生命周期**
  （创建 → 进 → 出 → 获取 → 修改 → 传递）；存储退为四模块之一，不再是内核立论起点。
- 已定 · **唯一引擎 = 信号处理器**：`Signal` **就是一种解析器**——解析 `Event` 包，按包内字段
  解析到**实际角色**，形成**有效动作**。内核逻辑只剩这一处；四个模块本身不带逻辑。
- 已定 · **对象集合 = 5 个**：`Core`（门户／能力提供 + **对象实例管理**）、`Signal`（解析器）、
  `Storage`（对象进／出）、`Conf`（参数真源）、`Event`（门户入口，非模块）。
  新对象须回答"实例管理 or 能力提供"，两者都不是即不属内核。
- 已定 · **`Event` = 门户入口，性质近消息协议**：由「**动作 + 行为描述**（+ 可选**承载体**）」完整
  描述一种事件形态。**不进存储**；单机是内存生命态，网络是数据流、到达即**重新序列化回对象**。
  **对象实例不随包走**：包里给可辨识信息，实例由 `Core` 的实例管理取出。
- 已定 · **工具单元**：承载工具语义的静态单元，**无逻辑、无状态、不执行**，形态不强制
  （对象 / 装饰器 / 类型皆可）。**`Attr` = 「字段的高级标注工具」，归工具单元**（迁出存储是
  **归位**不是搬家——它本来就不是存储的东西，属静态解析）。与 `ui_tools`（界面脚手架）毫无关系。
- 已定 · **旧门户直接清理、重新做一套**（不做兼容、不并存）：地址树 / `Action` / `Topic` /
  `Domain.bind` / `EventBus` 的旧形态清掉。
- 已定 · **`Vault` 解散**：不属 5 对象之一；持桶归 `Storage`，能力与实例管理归 `Core`。
- 已定 · **历史概念默认动作 = 删**：旧概念若无法映射到 5 对象之一、或无法表达为工具单元的标注，
  就没有容身之处，直接清理，不留兼容层。
- 已定 · **判定标准四条**：① 逻辑只有一处（能归约为"解析包 + 决策"）；② 加领域 `core` 不新增概念；
  ③ 换实现不得改语义、不得改第二处；④ 没有两套同类机制产出同一类事实。
- 已定 · **存储最小变更**：只做**职责剥离 + 增量**（剥离通知 / 编排 / 领域语义 / 立论起点；
  对象与块分离），**不借机重写**。
- 已定 · **分期**：M0 规格 ✅ → M1 门户与实例管理（`Core` + `Conf` 经门户可达）→ M2 `Event` 与解析器
  → M3 工具单元（`Attr` 归位）→ M4 存储剥离。
- 遗留（不阻塞）· Q3 `Data` 去留（合入 `Attr` or 独立）/ Q2 门户强制程度（倾向完全经门户）/
  Q4 `Event` 因果链（网络侧再定）/ Q5 工具单元边界（倾向只做构造与组合，编排归解析器）。
- 2026-09-24 · 待定（Q7 重述）· **版本能力装回哪儿**：现状是能力**已被摘掉**（`VersionStore` 与
  `core/storage/version.py` 不存在、全库无一处写版本表），不是"两处直连待收口"。规格 §5.1 的
  **A**（`Storage` 提供 `versions(oid, codec)`，域只给 `Codec`）/ **B**（域经门户自带表，版本引擎留域侧）
  仍都成立；但 **`Note.save` 的现存注释是"版本由领域日后自建"（倾向 B）**，与规格"倾向 A"不一致。
  **裁定前不要按任一侧动手。**
- 说明 · **本方向推翻本文件以下旧决策**：`kernel.md` §1.6「通信主干 = 统一调用总线」、
  `ui-kernel.md`「通知非命令」→「统一调用主干」两版、`storage.md` 公理「上层一切最终都是块」
  （收窄为存储内部表示）、`domains.md`「`XxxData(Block)` + `Xxx(Domain)` 两分支」（待重定）。
  **架构文档章节待 M1 落地后按代码回写**（届时按本方向定向改）。

## 通信主干 = 统一调用总线（2026-09-19，方向定）

> ⚠️ **2026-09-22 作废**：主轴改为「对象主干 + 事件对象」，`Signal` 是**解析器**不是调用总线；
> 旧门户（地址树 / `Action` / `Topic` / `EventBus`）清理重做。以下仅存档，勿据以实施。

> 取代旧口径「通知非命令」（`ui-kernel.md` §3.1.1，待回写）。

- 已定 · **定性**：这不是「事件总线 / 通知」，是**进程内统一调用主干（对象寻址空间）**。
  单进程、函数级、同步，无网络 / 无投递保证 / 无 ack；「通知」塌缩为命令，差别只剩**单播 / 多播**。
- 已定 · **三向通信同一机制**：内核↔内核、领域↔领域/内核、UI↔（内核+领域）。
  边界=**跨内核 / 跨域 / 跨 UI 才上主干**，域内正常函数调用不上（否则退化为动态消息系统，mypy 报废）。
- 已定 · **寻址零字符串、静态声明树**：`Signal.<ns>.<Domain>` 属性访问拿地址；
  动作侧也是**句柄对象**（`Signal.feature.Note.save`），不是字符串。树须静态声明，否则 IDE / mypy 全失。
- 已定 · **树节点 = 域服务单例**（处理器级对象，数量少、以单例为核心）；数据实例不进树，
  动作以目标 id 作参数（形态 A 为主；实例代理 B 仅作 UI 便利糖）。
- 已定 · **旧字符串命名信号层已移除**（`core/signal` 的 `SignalBus` / `SignalEvent` / `check_name`
  与 `Vault.signals`、其测试）：与零字符串地址树冲突，清了地面再建新主干。
- 已定 · **失败 / 返回**：进程内、Python 直接抛。命令通道**不得吞异常**
  （现 `EventBus.emit` 吞异常，`events.py:104`，须拆）：命令透传、多播才谈隔离。
- 已定 · **单例作用域 = 每 App / Vault 一个**，不做模块级全局（测试隔离，非并发考量）。
- 已定 · **UI 红线**：UI 只发命令 + 只收事件，不允许经主干点对点直调域对象内部。
- 已定 · 多播（邮件型）接收者抛异常**隔离继续**（沿用 `EventBus` 语义）；单播命令异常**透传**。
- 已定 · 树根名 **`Signal`**（旧字符串信号类已删，无冲突）；命名空间 `core` / `feature`。

### 实现（2026-09-19，已落地）

- `core/signal`：`Signal`（主干 + 地址树）/ `Domain`（域服务基类）/ `@action`（单播动作描述符）/
  `Topic`（多播信号描述符）/ `Action` / `BoundTopic`。单播经 `invoke`（异常透传），多播复用
  `EventBus`（异常隔离）。零字符串：`signal.feature.Note.save(...)`。
- **不做动态注册 / 内省**：域容器由**组合根静态声明**（`class Feature: Note: Note`），`signal.feature = feature`
  普通赋值挂上；`Domain.bind(signal)` 显式绑总线。删掉了 `Namespace.__getattr__` / `Signal.register` / 字符串 setattr
  ——动态注册**无人受益**（所有使用方都静态知道领域名），属过早泛化。
- **未绑定的域**：动作退回直接调用（便于单测与内部自调用）；`bus` 属性报「未绑定总线」。
- 作用域每 `Signal` 一实例；域容器按层静态挂载（`core` / `feature`）。

## 领域服务 / 数据分离（2026-09-19，方向定 + 已落地）

- 已定 · 领域拆两层：**`Note` = 域服务（单例；机制 / 策略，类比 `sys`）**
  + **`NoteData(Block)` = 纯数据**。
- 已定 · 数据由 **Bucket 与域服务共同管理、各管各的**：Bucket 管存储
  （oid / checksum / 内容池 / 目录 / 事件），域服务管语义（创建 / 读写 / 版本 / 关系 / 策略）。
- 已定 · 落地：`NoteData` 保留字段 + 纯内容操作（set_text / 行级 / 样式 / 段落 / blocks / references）；
  `Note` 提供 `create` / `load` / `list_notes` / `save` / `persist` / `update` / `history` / `body_at` /
  `restore` / `link` / `add_canvas` / `add_access`，并声明 `changed` 多播。版本基线 `_saved_state` 随数据。
- 已定 · 其余领域（Project / Canvas / Group …）尚未拆，按同一口径推进。

## 数据库重构（2026-09-19，方向定 + 切片 1–3 已落地）

- 已定 · **现状 8 张表**：内核 `packs` / `contents` / `blocks` / `meta`；按需 `search` / `versions` /
   `version_heads` / `relations`。问题：无「表政策」，可派生冗余（`version_heads`）与内容副本（`search`）。
- 已定 · **`block` = 物理事实表**：`oid`（+ 至多相对物理地址）、`type`（**整数枚举**，非字符串）、
  `body_id`（→ body 池）、`size`、`created` / `updated`，外加**块自身数据 / 配置**（对象携带的字段
  序列化在一起，不再拆 `author` / `config` / `meta` 多列）。
- 已定 · **block 层不去重**（无意义）；去重在 **body 层**：body 以**哈希**为 id，同内容只存一份；
  `block.body_id` 引用 body。
- 已定 · 载体文件**随机哈希命名**（`[0-9a-z]` 的 32 / 64 位），废弃顺序 / 语义命名（`000001.pack`）。
- 已定 · **body 表保留原表名**，只把字段改成自解释（键列明确为 `body_id`）。
- 已定 · **域表不复制块内数据**：note 自身配置 / 属性已在块里，域表再存一份 = 重复 + 一致性地狱。
  域表只放**关系 / 组织**。
- 已定 · **多对多关系走独立边表**（一列塞不下）；边表**跨域共享**（note / project / group 都用），
  加 **`domain`（领域类型）** 字段区分归属。
- 已定 · **组仍是块**（`cairn.group`，实体真源，管嵌套 `group: list[str]`）。**不另建组索引表**：
  `block.type` 整数码 + `idx_block_type` 索引本身就是领域枚举——`Group.list` = `block WHERE type=group`，
  无需双写、无一致性问题。
- 已定 · **表名规范：单数、直白**。候选：`block` / `body` / `note` / `project` / `group` /
  `group_index` / `relation` / `version` / `search`。现名 `contents`（概念是 body 池，**不叫 body**）、
  `blocks`、`relations` 等改为直白名。
- 已定 · **不建 `note` / `project` 领域表**（推翻早先「每域一张表」）：其诉求已分别由
  ① `block.type` 整数码索引（枚举 / 计数）、② 跨域 `relation` 边表（关系）、③ `cairn.group` 块（分组）
  满足；再建域表只会复制块内数据，违反上条「域表不复制块内数据」。域表仅在确需「不重复块数据的
  可查询面」时才建（当前无此需求）。
- 已定 · 全局搜索保留，但**不用纯字符串全库扫**（易拖垮库）；方向 = **混合搜索**（向量 + 全文 / 精确），
  实现待定。
- 已定 · **笔记本身不去重**；去重**只在 body 层**（`body.id` = 哈希，作去重键；库里那一行只为
  「哈希 → 物理位置」）。域表 `id` 用于**引用**，稳定，不承担去重。
- 已定 · **原则**：数据库只放「要定位 / 要引用 / 要去重 / 要查」的东西；**内容本体在 pack，不在库**。
  body 行在库纯为去重索引。
- 已定 · **版本**：先留库（`version` 表即可，去掉可派生的 `version_heads`）；**版本膨胀是后续升级问题**，
  届时可专门出「版本块 / version block」外置。现在不阻塞。
- 已定 · 表名按单数直白规范：`block` / `body` / `packs` / `meta` / `note` / `project` / `group` /
  `group_index` / `relation` / `version` / `search`。
- 已定 · **迁移策略**：`catalog_version` + **增量迁移**（开发期可手跑 SQL；每次改 schema 递增版本并写迁移步骤）。
  表分两类：**真源表**（`body` 位置索引 / `relation` 边 / `version` 链）需真迁移；**投影表**
  （`note` / `project` / `group_index` / `search`）可 **drop + 从 block 重建**。
- 已定 · **长期方向**：让权威数据尽量落 **block**，DB 退为**可重建的索引 / 投影**——届时迁移 ≈ 重建索引。
  前置：版本外置为「版本块」、关系内嵌进块（`relation` 退为投影）；代价是双写。
- 待定 · `search` 是否并入投影 / FTS5 / 向量库（混合搜索实现待定）。
- 已定 · **`type` 整数码表已落地**：`block_type(code, name)`；core 预置 `0=block / 1=part / 2=index`，
  其余首写自动登记（`Catalog.type_code` / `type_name`），**码分配后不复用**；core 不硬编码领域名。

## 编排 / App 层（2026-09-19，方向定 + 目录已落地）

- 已定 · **内核 / 领域 / UI 各自独立定义**，之间是**垂直依赖**；由此自然产生的新层是 **App**——**不是再造一个
  "kernel" 层**（此前 `src/kernel.py` 的编排尝试已撤除）。**App = 组合根 / 编排层**：组合内核 + 领域 + UI，并按平台发布。
- 已定 · **发布布局在 `src/app/<平台>/`**：`win` / `linux`（macOS 等顺加）；`src/app/__main__.py`、
  `src/app/win/{main,backend,windows}`。
- 已定 · **`ui_tools` 原地不动（工具箱）；实际 UI 载体在 `src/app/<平台>`**（`win/`）：从内核取数据、用
  `ui_tools` 组装窗口。**平台策略**：Windows 真上；Linux 不要 UI；macOS 暂缓；Android 未来另择 UI 框架
  （Qt 上安卓不划算）。
- 已定 · App 组合落地：`app.Feature`（静态域容器）+ `app.build(vault)`（Session/App/Facet）；领域 UI
  `NoteFacet` 在 **App 侧**（`src/app/facets.py`），**不进 `ui_tools`**。
- 已定 · **目录重定**：`src/core`（底座；含新 `core/conf` 配置 / 常量）/ `src/feature`（领域）/
  `src/ui_tools`（界面工具层，原 `src/ui`）/ `src/app`（应用）。**删除** `src/conf`（并入 `core/conf`）、
  `src/net`、`src/server`。
- 已定 · **撤销 `feature/_shared`**：跨域协作不靠"共享层"，改由 **App 承担编排**；`relation` / `provenance` /
  `signature` 回 `feature/` 顶层（`_shared` 已删）。跨域协作的确切形态待 App 落地时定。
- 已定 · **`core/conf` = 统一配置 / 常量内核化**：把散落的配置 / 常量集中（便于查询 / 管理 / 不发生混乱崩溃）；
  用途仍在明确（`core.py` 已有 `FORMAT_VERSION` / `TOML_NAME` / `VAULT_META_CONTEXT` / `VERSION_WINDOW_MS`）。
- 已定 · UI **不是**统一领域的东西（它只是消费方）；App 才是。`ui_tools` 是**工具箱**，不放入口 / 领域 Facet
  （已删 `ui_tools/app.py`、`ui_tools/note.py`）。
- 待定 · 剩余横向依赖：`note → canvas`（`canvas` 已升格为块域，却被 note 当共享类型用）——
  需定 `canvas` 算共享内容类型还是独立域；跨域编排整体归 App，待落地。

## UI 内核修正（2026-09-19，Facet 分析 ≠ 领域契约）

> 对齐 `ui-kernel.md` §4「对象驱动生成」；修正上一轮"撤销"过头。

- 已定 · **撤销的是「领域额外写契约」**（要求每个领域先声明一份 fields/actions/signals 清单），
  **不是**对象驱动生成本身。领域**无需额外作者化**——它的"契约"就是对象自身已有的声明：
  字段（`Attr`/`Data` 注解）、动作（`@action`）、信号（`Topic`）。
- 已定 · **`Facet` = 分析器 + 组织器 + 包装器 三合一**，是整套体系里**最重**的一环，其余皆辅助。
  交付 = 一个完整的**领域 UI**：页面 / 组织 / 布局 / 组件 + 信号绑定 + 路由配置；最终交给 `App` 注入，
  并告知"这块 UI 放哪 / 怎么嵌"，由 App 生成整套页面。
- 已定 · **分析是浅的、确定性的**（达不到代码生成器级，只做确定性动作）；**确定性来自定义位置**——
  **全部写在 `Facet.__init__`**：`self.xxx = …`（属性配置）、`.add(...)`（组织 / 布局 / 组件）、
  `.bind(...)`（绑定）、`.navigate(...)`（路由）。**这份 `__init__` 内容天然就是该 UI 的契约与约定**，
  实例化即成立；后续代码只在其上影响计算与生成，不做运行时推断。
- 已定 · **`Facet` 声明 API（简化为两条）**：
  - **页面**：`self.page(page, route_signal)`——页面对象 + 路由信号，一个 API。页面切换就是"注册页面 + 用哪个信号切过去"，无更复杂机制。
  - **绑定**：`self.bind.add(source, target)`——`self.bind` 是 Facet 持有的**登记处对象**（名词），随 Facet 生命周期释放；
    `source` = UI 信号（明确到信号），`target` = 领域动作（`self.note.favorite`）或本类方法（`self.on_clear`），同一种写法。
    不用裸 `Bind()`（无主、泄漏）、不用动词式 `self.bind(...)`（无法带 `when` / 转换参数）。
- 已定 · **`Facet` 配置 API**：`self.conf.theme.set(点分路径, 值)` / `self.conf.<域|组件>.set(键, 值)`——
  **单点赋值**，清晰、可 schema 校验、不链式；`self.conf.theme = …` 只用于**整体替换**（少用）。
  `theme` = 封闭词表（外观令牌，唯一真源，组件只引用 `token.*`、禁硬编码）；
  `attr` / `ui` = 开放词表（组件 / 页面行为配置，Facet 主要在此 `set`）。
- 已定 · 配置不止 `set`，**`add` 同样要有**（属性可加、样式可加）。底层 Qt 支持动态样式：
  QSS 可全局 / 逐控件追加并 `unpolish`/`polish` 重算；动态属性选择器可做状态驱动。
  `set` = 覆盖已有键；`add` = 新增键 / 规则（**须过 schema**，不得破坏封闭词表）。
- 已定 · **配置 = 一株有向路径树**：绝对路径 `app.<域>.<page>.<layout>.<com>…:<item> = 值`（嵌套多深链就多长，
  **超长无妨，求确定性**）；`{}` 写多项，`:item = 值` 为 CSS 式高级写法。
  - **两个面、一套词汇**：Facet 代码面 `self.conf.<组>.set(局部路径, 值)`；文件面写绝对路径，编译后同一套。
  - **App 持有 schema**（由 Facet 树自动生成），统一获取 / 计算；IDE 据此校验路径。
  - 同一路径下 `attr` 自由、`theme` 只认词表令牌项。
  - 副产品：**路径 = 布局结构** → 改配置即改布局，未来 `CairnThemeTools` 可据此做可视化布局（对应 `ui-kernel` §6「拖布局 = 改文件」）。
- 待定 · 配置的第三式 `bind`（样式随状态 / 信号变）：技术可行，但与事件绑定 `Bind` **撞名**，
  建议改名 `when` / `state`；状态样式需 repolish，按 `ui-boundary`「逐条加、可测、有边界」推进。
- 已定 · 字段不写死：由**内核提供中立内省**（对象结构 → 中性视图；UI 不 import `core.storage`），
  `Facet` 读它生成；`label` / `group` / `display` / `editable` 只是可选显示提示槽位。
- 已定 · **领域在组合根硬标注，不做运行时推导 / 稳定代理**：领域数量少（≤10）且确定，不像插件那样不可预知，
  直接在组合根显式 `signal.register(Note)`、写死 `note` / `project` 即可。`Signal` 的命名空间机制保持通用，
  但**不做内省 / 推导**；**领域契约 / 从插件推导 UI 只在未来引入插件系统时再上**（届时基于本底层）。
- 可选 · **地址树静态声明**（IDE 友好）：`signal.feature.Note` 目前是动态 `__getattr__`，IDE 不补全；
  若需要，可在组合根层**静态声明**命名空间属性 + 类型（领域少、代价低）。非必须。
- 已定 · **红线不动**：`Facet` 收的是**注入进来的领域对象**，自己不创建，故**无需 import `feature`**
  （类型提示可选，`object` / 鸭子类型即可）；"UI 不 import `feature` / 不碰 `Vault`" 继续有效。
  真正认识领域的只有**组合根**（创建服务并注入），不在 UI 内。

## UI 根布局与风格（2026-09-21，Windows 壳起步）

- 已定 · **根布局三带**：顶带（工具栏，相对固定）+ 舞台（自由度最高的主区）+ 任务栏（长期任务）。
  边缘（导航 / 检查器 / 关系 / 版本）按需出现、默认收起；专注时全隐。
- 已定 · **捕捉与整理 = 同一空间换态**（不另开捕捉窗）：浏览（卡片流）/ 专注（一卡占满）/ 组织（看板 / 画板）。
- 已定 · **笔记与项目同构**：舞台只有「卡片」一种单元；项目 / 组 / 标签是**镜头（过滤器）**，不是顶级分区。
  「进项目」= 换镜头，不是换世界。以此兑现最早的「融合」诉求。
- 已定 · **卡片四粒度**：卡 → 展开（卡内编辑）→ 专注（占满）→ 落板（拿空间坐标）。
  卡自带位置属性，规则视图是派生、画板是手动覆盖。
- 已定 · **两种密度**（照 Windows 资源管理器，只留两种）：卡片（大 / 中图标）/ 详细（列表）。
  笔记与项目混排，靠 `kind` 颜色区分（note 蓝 / project 赭）。
- 已定 · **软质感**：低饱和冷灰底 + 少量暖赭点缀，圆角、柔和阴影、留白、半透明「毛玻璃」近似；
  真 Acrylic（Windows DWM）另立，不假装已实现。
- 已定 · **顶带 = 工具栏**：搜索 / 命令常驻；其余功能走**伸缩抽屉**。
- 已定 · **工具底座 = 大方框 + 格子 + 槽（无任何业务词汇）**：`App.root` 是空的大方框，作者用
  `set` / `add` / 嵌套自由搭出任意结构（三栏 / 异形都行）；`Slot`（命名槽位）用 `expects=` 声明
  等谁的哪个部件。**工具里不留 `topbar` / `navigator` / `content` 这类预置区域**
  （上一版 `SuperLayout` / `TopBar` / `TaskBar` 已删）。
- 已定 · **谁定义标签，标签归谁**：App 的槽名 App 起，Facet 的部件名领域起，**不代定义**。
- 已定 · **`App` = 根 / 定义，`Facet` = 子件**：`App.add(facet)` 遍历结构里的槽，按 `expects` 取
  `facet.parts()` 同名部件填入。Facet 说领域话（`parts()`：`page` / `nav`…），App 说 App 话
  （槽名 + 填充规则）。**组件 / 布局只被 Page 或 Facet 消费；App 不直接吃组件 / 布局。**
- 已定 · **槽只管自己的行为**（弹性 `stretch` / 滚动 `scroll` / 顶对齐 `align` / 隐藏 `hidden` /
  锁死 `locked` / 容量 `capacity`），**不管内容怎么显示**——内容显示是组件自己的事，别本末倒置。
- 已定 · **`Surface` = 带外观的通用容器**（背景 / 圆角 / 可选投影），App 搭格子用的普通组件。
- 已定 · **实现归位**：机制进 `ui_tools`，组装与数据进 `app/win`（`windows/CairnApp` + `NoteFacet`
  + 主题加载，`backend/` 投影），外观进 `config/theme/*.json`。**壳不得绕开 `ui_tools` 用裸 Qt 搭**。
- 已定 · **增长只在 `ui_tools` 目录**：加组件 / 布局 / 页面就进 `component/` / `layout/` / `page/`；
  **内核非必要不修改**（仅当内核确实不支持时才动）。
- 已定 · **UI→UI 绑定用动作句柄**：`Node.action(方法名)` 返回 `NodeAction`，编译期解析到控件方法
  （密度按钮 `.clicked` → `stage.action("toggle_density")`），不把 Qt 控件泄进声明层。
- 已定 · **外观唯一真源 = `config/theme/*.json`**：由 `ui_tools.core.load_theme` 加载，`App.theme` 持有，
  卡片委托按令牌取色；壳不再自带硬编码色。默认 GitHub 色盘（`github-dark` / `github-light`），改盘待定。
- 已定 · **领域 Facet 自带视图控件**：卡片 / 详细密度切换归笔记 Facet（内容自带），不进 App 顶带（免跨层）。
- 方向 · **对象驱动生成（待落）**：把领域对象交给 `Facet` 应自动产出卡片 / 字段 / 配置等机械件，
  作者只写领域页面本身；当前卡片提取器仍是手写，属下一片。
- 已定 · **`App` 拥有生命周期与启动**：`CairnApp.open()`（开库 + 组装）/ `.run()`（套主题 → 建窗 →
  事件循环）；`main` 只剩一行 `CairnApp.open().run()`。Qt 启动实现放 `ui_tools.core.qt.run`（Qt 边界），
  `core` 仍 Qt-free。**不把 Qt 启动样板与两步 `build` 暴露给使用者**（上一版作废）。
- 进行中 · 第一片（App 级根壳 + 笔记 Facet + 真实数据 + `ui_tools` 管线 + config 主题）已落；
  自动生成 / 抽屉 / 任务栏真实任务 / 边板 / Acrylic / 笔记编辑页待续。

## 领域层定义（2026-09-21，方向定）

- 已定 · **继承定身份**：`Block` 子类 = 存储数据结构；`Domain` 子类 = 域。**无第三态**。
- 已定 · **域 = 管理型对象、单例、无 ID**；`type` / `name` / `data`(依赖的数据结构) 用**类属性**声明，
  基类填默认（`__init_subclass__`），子类只写差异。给域 ID 立刻引发"改哪个"的一致性问题。
- 已定 · **数据项（`XxxData(Block)`）有 ID**：`id / type / name / summary / stamp / tags / flags` 是
  UI 可用的**最小数据结构**；卡片呈现的是**数据项**，不是域。
- 已定 · **真域目前只有 Note + Project（占位）**；`Asset` / `Canvas` / `Group` 是**存储数据结构**
  （**已降级**：`Domain` 服务删除，构造入口落在数据类 `AssetData.create` / `CanvasData.create` /
  `GroupData.create`，组操作成 `GroupData` 方法）。
- 已定 · **最小类型表**：`core/types/kind.py` 登记 `TypeInfo{type, role, name, fields, deps, unit}`；
  `role` = `domain` / `data`；域与数据**可同名**（`Note` 与 `NoteData` 都是 `cairn.note`），按
  `(type, role)` 分键。定义时登记（`Block` / `Domain` 的 `__init_subclass__`），运行时只读。
- 已定 · **最小数据 = 指针，不是字段表**：域上 `light = XxxData` 或 `light = (XxxData, …)` 绑定**既有
  数据类**（最小数据单元，可多个）；`TypeInfo.units` 存其 `type` 名元组。**公共锚点 = `Block`**——
  任何单元都能顺着往上找：`unit_infos(type)` 顺下取单元、`domain_of(unit)` 反查所属域。
  **禁止另立最小字段表**（重复维护）。
- 已定 · **类型以声明为锚，继承只做实现复用**：跨边界（落盘 / DB / UI）继承链不跟随，推理必须靠
  `type` 字符串（计划补 `role` / `fields` / `deps`）；不做通用类型系统，词表封闭即可。
- 已定 · **`Attr` / `Data` 是通用字段描述符，归 `core.types`**（`core/types/attr.py`）；
  `core.storage` 继续 re-export 兼容。任何"属性"都能用 `Attr` 声明。

## 领域文件组织（2026-09-21，方向定 + 第一批已落）

- 已定 · **`feature/` = 域 + 共享件**：`note/`、`project/` 是**域**；其余全进 **`shared/`**——
  数据结构（asset / canvas / group）、值（signature）、设施（relation / provenance / base）。
- 已定 · **`note/edit/` 拆三块**：`body`（行身份 / 占位 / 规范化）/ `text`（文本增删拆合）/
  `style`（行内区间样式），**不引类**（纯变换就该是函数）；`edit/__init__` 仅作兼容转出。
- 已定 · **领域代码里别用 `from .edit import body, style, text`**：`text` / `style` / `body` 会与
  方法的参数 / 局部名相撞（已踩）。用 `from . import edit` + `edit.<块>.<func>`，或子模块具名导入。
- 已定 · **`note/` 职责归位**：`data.py`（数据描述：值类型转出 + `NoteBody` + `NoteData` 载体 + 读视图）/
  `edit/`（纯操作原语）/ `service.py`（`Note` 域服务，**全部操作以 data 为首参**）；工具签名
  `run(svc, data, ctx)` / `state(data, ctx)`。`NoteData` 只留字段 + `body_hash` / `text` / `style` /
  `paragraph` / `references` / `_state`；值类型 `Style` 在 `edit/style.py`。
- 已定 · **`Domain` 声明**：`name` = **模块路径（解析键，不是显示名）**、`type` = `Kind.Feature.*`、
  `data` = 本域用到的**数据类元组**（`body` 免列）、`light` = **最小数据单元列表**。显示名归 UI（不写死）。
- 已定 · **`Show`（UI 侧投影，`ui_tools/core/show.py`）**：最小数据单元（可多个）→ 显示素材；
  L0 归集（attrs 合并 / ids 全并 / body 收集）→ L1 按来源类型分组 → L2 字段默认呈现 →
  L3 body 感知；**L4 语义推断不做**。由 `Facet` 内部使用，开发者不直接碰。
- 已定 · **类型枚举（重定）**：`feature/shared/kinds.py` 的 `Kind` 分两支——`Kind.Feature`（域：`note` /
  `project`）与 `Kind.Data`（数据：`notedata` / `projectdata` / `canvas` / `asset` / `group`），
  **plain `Enum`、值去 `cairn.` 前缀**；域与数据不再共用同一字符串。类型表键按值归一
  （`core.types.type_name`），枚举 / 字符串可互换；第三方仍可用自有前缀字符串。
- 已定 · **类型命名空间 `cairn.<domain>.<kind>` 作废**（无旧数据）；官方类型以 `Kind` 为准，
  块落盘的 `type` 就是枚举值（如 `notedata`）；core 的 `block` / `part` / `index` 与关系 `relation` 同步去前缀。
- 提醒 · 早先"撤销 `feature/_shared`"针对**跨域协作 / 编排**（归 App）；本条是**共享类型与设施**，不冲突。

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
