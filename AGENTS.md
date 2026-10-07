<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# AGENTS.md

Cairn（巨石堆）：本地优先的内容寻址对象池 / 笔记·资产·项目工作台。Python 3.14；内核 Qt-free。**当前在位的是内核、领域形状层与 Python 边车**（`py_src/core/`、`py_src/model/note/`、`py_src/app/sidecar.py`）；`feature` 随 2026-09-29 的重建删除、待重建，界面材质为 **Tauri 壳 + Web 前端**（`app/` 是那份 Tauri 工程，功能未齐）——现状与意图的对照见 `docs/architecture/index.md`。用 `uv` 管理；Apache-2.0。

## 开工前 SOP（每个任务都先做）

1. **先看规则**：判断当前任务命中哪条规则，只读相关的那条；没有命中的规则就跳过。
2. **再看记忆**：读与本次任务相关的**决策**与**进度**，摸清现状。
3. **再动手**。

细则都在 `.agents/skills/`；本文件只做**索引与红线**，不要把长规则堆在这里。

## 常用命令

```powershell
uv sync                                   # 安装/同步依赖

uv run pytest                             # 全部测试（含覆盖率；CI 用 --cov-fail-under=80）
uv run pytest tests/core/test_engine.py::test_store_then_load_roundtrip   # 单个测试
uv run ruff check .                       # lint（--fix 自动修）
uv run ruff format .                      # 格式化（提交前用 --check）
uv run mypy py_src tools scripts tests    # 类型检查（strict）
uv run python scripts/spdx.py --check     # SPDX 头门禁（缺头用 --fix 自动补）
uv run python scripts/prose.py            # 书面语门禁（文档/注释不得口语，词典即标准）
uv run python scripts/punct.py --report   # 标点检查（注释/docstring 的中文标点；报告模式）
uv run deptry .                           # 依赖盘点（声明了没用 / 用了没声明）
uv run lint-imports                       # 架构校验（契约在 pyproject 的 [tool.importlinter]）
uv lock --check                           # 锁文件是否与声明同步

uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
                                          # **先装钩子**，否则下面这条与提交时的门禁都不跑
uv run pre-commit run --all-files         # 提交前全量门禁（13 个钩子；清单见 quality.md §4）

uv run mkdocs serve                       # 文档站本地预览 -> http://127.0.0.1:8000
uv run mkdocs build --strict              # 文档站构建门禁（坏链接/缺页面/未知配置即失败）
uv run python scripts/docgen.py --check   # 生成页防漂移（配置参考 vs 入库词表 + AST 扫的声明处）
uv run python scripts/docgen.py --write   # 重新生成配置参考页（改了配置声明后跑）
uv run python scripts/docgen.py --coverage # docstring 覆盖报告（没写的公共成员会从 API 页消失）
uv run onconf check --home config --strict # 配置声明门禁（**--home 必给**：CLI 缺省是 ./conf）
uv run onconf build --home config          # 按声明完整重建 config/ 下那两份入库产物

pnpm --dir app check                      # 前端门禁（类型/lint/样式/架构/令牌/重复代码/单测，七道合一）
pnpm --dir app gen:tokens                 # 由 config/theme/tokens.json 重新生成令牌 CSS
pnpm --dir app tauri dev                  # 起桌面外壳（开发）
```

> 桌面外壳（Tauri 壳 + Web 前端）已在 `app/` 立项（脚手架、图标与名字都换成 Cairn）：
> 边车 `py_src/app/sidecar.py` 与前端转发口 `app/src/ipc/index.ts` 已接线，**界面功能未齐**。
> 旧打包脚本（`scripts/build.py` 与 `build-windows.yml`）依赖 Qt 时代已删除的层级，**待重做**。
> **前端门禁已接线**（`pnpm --dir app check`，七道合一；pre-commit 只在 `app/` 变动时跑，
> CI 走 `web` job）——规矩与门禁的对照表见 `rules/references/frontend.md` §四。
>
> 配置投影**没有生成脚本**：跑一遍程序即可（值文件与词表在提交点落盘），
> 入库产物与声明是否分叉由 `tests/core/test_conf_projection.py` 拦
> （拿空目录里新生成的那一份当基准，读当前这份再比是自证）。

提交前顺序：`ruff -> mypy -> pytest`（全量一次跑完用 `pre-commit run --all-files`）。
质量口径见 `.agents/skills/rules/references/quality.md`
（企业级-ε：mypy strict、ruff ALL、warning 零容忍、覆盖率 ≥80%）。**只有用户明确要求才 commit。**

## 硬性约定

- 每个源文件/文档顶部必须有 SPDX 头：`SPDX-FileCopyrightText: 2026 HanYang06`
  + `SPDX-License-Identifier: Apache-2.0`（`.py` 用 `#`，`.md` 用 `<!-- -->`）。
  **不得手写**：pre-commit 自动补、`scripts/spdx.py` 校验；装不下头的（图片 / JSON / 锁文件 /
  vendored）走 `REUSE.toml` 集中声明。细则见 `rules/references/spdx.md`。
- Apache-2.0 项目：**禁止引入 GPL/AGPL 依赖**（传染红线）；第三方主题/画布库先核实许可。
- 文档、注释、commit message 用中文；commit 用 Conventional Commits（`feat(ui): …`、`fix(core): …`）。
- 不写 C++。Rust 已正式进入技术栈：桌面外壳用 **Tauri**（壳本身就是 Rust），
  另保留"把 Python 性能热点下沉到 Rust（PyO3 + maturin）"这条路，触发条件是热点被证实。
  **壳里不写业务**——判断句：换掉界面之后仍然该存在的逻辑，不属于壳。
- **`tools/` 与 `scripts/` 按"能不能被 import"分**（两者不混）：
  `tools/` 是正规包，可 `from tools.<模块> import …`，装**产品与流程用得着的可调用件**
  （mypy 插件、原子写与输出助手）；`scripts/` 装门禁、生成器与打包，**不放 `__init__.py`**
  （声明它不是包）。注意这只声明意图——Python 3 的命名空间包仍可 import，
  **真正的拦截是 import-linter 契约**：`core` 与 `tools` 不许依赖 `scripts`。
- 未实现的设计标为「预留/草案」，不要假装已存在。
- **文档分两类，别混**：手写事实源在 `docs/**/*.md`（跟代码一起评审）；
  `docs/api/` 下的 API 参考与 `site/` 站点由 `mkdocs` + `mkdocstrings` 从 docstring **自动生成**，
  **不手改**。新增页面要登记进 `mkdocs.yml` 的 `nav`。细则见 `rules/references/docs.md`。

## 架构分层（别越界）

**现状**：`py_src/` 下在位的是 `core`（L0 内核）、`model/`（领域形状层）与 `app/`（命令面与内核边车）；
`feature` 随 2026-09-29 的重建删除，下面是它的**目标形态**（回来时按此落，别在 core 里提前实现）。

> **2026-09-30 起界面材质为 Tauri 壳 + Web 前端**（React / TypeScript），Python 内核以边车运行。
> 故下面按 `py_src/` 描述的分层只覆盖 Python 一侧；界面侧的边界见
> `rules/references/ui-boundary.md`。**`ui_tools` 这个层名随 Qt 作废**，其职责由前端共享组件承担。

- **源码根有两个，名字不重**：Python 在 `py_src/`，前端在 `app/src/`（React）；
  Rust 壳在 `app/src-tauri/`。**顶层包在 `py_src/` 下、一律去 `cairn.` 前缀**（`from core.storage import …`）。
- `py_src/core/`（L0）是公共底座：**必须 Qt-free、传输无关**。当前装着三件事：
  **事件引擎**（`core/event/`：`Event` / `Bus` / 事件目录）、**存储层**（`core/storage/`：
  载体与槽 `pack.py`、hub `hub.py`、声明 `types.py`、配置声明 `conf.py`、
  存储引擎 `engine.py`、回收 `gc.py`；身份与段算术、载荷与索引库在 `db/`
  （`id.py` / `payload.py` / `engine.py`）；两类索引块在 `index/`）、**异常层**（`core/exc.py`）；
  装配在 `core/init.py` 的 `Kernel`，时间口径在 `core/clock.py`，**配置**在 `core/conf.py`
  （只做装配：定配置根 + 关控制台日志出口；**引擎是上游 PyPI 包 `onconf`**，`conf` 直接用它的，
  声明各归各家——内核那条在 `core/params.py`、存储那组在 `core/storage/conf.py`，
  见 `docs/architecture/py_core/config.md`）。
- `py_src/model/`（领域形状层）：`model/note/types/` 落五个载体（`NoteData` / `NoteTag` / `NoteGroup` /
  `NoteAsset` / `NoteCanvas`）与值对象（`NoteLine` / `Span` / `Figure` …）的形状，见 `decisions/笔记.md` §四；
  **缺规范化字节层**（`model/note/format/` 不存在，`NoteData.lines` 里的行对象还存不下去）。
- `py_src/feature/`（L3）**待重建**：只依赖 core 公共 API，内部分**域**（`note` / `project`）与
  **共享件**（`shared/`）；域之间互不依赖；领域结构直接继承 `Block`，扩展只走子类字段、
  新 `type` 或新关系 `kind`。
- 类型词表（`Kind` 一类）随领域层重建再定：plain `Enum`、值即落盘字符串（如 `notedata`），
  第三方类型用自有前缀。
- `py_src/app/`（Python 侧入口：命令行与内核边车）：边车 `app/sidecar.py` 与命令面 `core/api.py`
  已落地，**缺一个面向人的命令行壳**；
  原「按平台分目录」的口径**随 Qt 作废**（Tauri 壳是跨平台的同一份工程）。
  界面侧**不认识领域内部、也不碰 `core.storage`**，只经契约与命令过边界。
- `py_src/net/`、`py_src/server/` 曾为 P2P / 服务端实验顶层包，**当前已删除、待重设**。
- 存储的路径约定只在 `core/init.py` 定：`<root>/catalog.db` 是索引库、`<root>/<hub>/packs/` 是载体。
- **权威顺序 `路线图 > 设计 > 代码`**：路线图（`docs/roadmap/1.x.md`）管「要什么」，代码管「现在是什么」
  ——路线图里对现状的转述与代码不符时，改路线图那一行。`docs/architecture/*.md` 是设计事实来源
  （`storage-design.md` 为 L0 存储的唯一事实来源），设计与代码往路线图收；改实现后回写文档。
  哪一页描述现状、哪一页只是意图，见 `docs/architecture/index.md`。
- 内部时间统一 unix 毫秒（`core/clock.py` 的 `now_ms`）；ID 的 `birth_time` 用纳秒。
  对象身份是 `core/storage/db/id.py` 的 `ID`：字段为 `name` / `value_uuid` / `birth_time`
  与位置段，另有**一项**库的事实 `body`（**当前那一份正文的摘要**，只有一个）。
  **2026-10-06 的裁定**：存储只做"记录与修改"——**不做版本、不做历史、不做安全**，
  世代、回滚、崩溃恢复由上层自行解决；
  **2026-10-02 的存储裁定把 `value_hash` 移出身份**（同日落码，见
  `docs/architecture/py_core/storage/block-parts.md`）。
  **同日的修正裁定**：**槽号只在 pack 内有意义**，ID 是跨 pack、跨 hub 的坐标，
  故"越 pack（甚至越 hub）的关联只能用摘要，不能用槽号"——"哪几格是属性槽"
  **不再是库的一列**，属性槽与正文槽靠槽头种类分辨（`pack.ATTR_SLOT` / `pack.BODY_SLOT`），
  正文的位置记在正文索引的位置行里（跨 pack/hub 的坐标）。

## 测试

- pytest：`testpaths=["tests"]`、`pythonpath=["py_src"]`，无需安装即可 `import core`。
- 测试无外部服务/数据库，全部用临时本地库。

## 环境与坑

- 库根由调用方显式给出（`Kernel.create(root)` / `Kernel.open(root)`）；**尚无库旋钮**——
  `CAIRN_VAULT` 一类的重定向随 App 或测试夹具重建再定。**本地不加密**（设计篇 §9.5），
  故没有口令 / 密钥类环境变量。
- 配置根有一个旋钮 `CAIRN_CONFIG`：只给测试与部署重定向，**不是配置项**
  （它是"找到配置的办法"）；不给就用仓根下的 `config/`。
- `.gitignore` 里仍留着 `vault/`（开发库的默认位置）：开发时别把库提交进来。
- Python 3.14；`uv.lock` + 阿里云 PyPI 镜像（`pyproject.toml` 的 `[[tool.uv.index]]`）。
  **`onconf` 是唯一例外**：阿里云镜像没同步这个包（实测 `simple/onconf/` 返 404），
  故 `pyproject.toml` 里给它单开了一个 `explicit = true` 的 PyPI 索引（只服务这一个包）。
- 图片走 Git LFS（`.gitattributes`）；未装 LFS 时 clone 到的 png 只是指针。

## 规则 / 记忆 / Skills（`.agents/skills/`）

- 技能统一放 `.agents/skills/<name>/SKILL.md`（跨工具目录：opencode、Codex、
  GitHub Copilot、Zed 等均读；opencode 全局版才用 `~/.config/opencode/skills/`）。
- 用 CLI 管理（skills.sh）：`npx skills add <owner/repo> --skill <name> -a opencode --copy -y`
  / `npx skills find <词>` / `npx skills update`。第三方技能保持上游原样，
  来源记在 `skills-lock.json`。
- 索引分工：
  - `rules` —— **规则总入口**，按场景分发到自己的 `references/`。规则只写这里。
  - `memory` —— **项目记忆本体**（可变、活文件）：**决策**（`references/decisions/`，一个主题一个文件、**只写现状态**、末尾带变更记录索引）与**进度 / TODO**（`progress.md`，只记"还没做"）。**不记变更流水账**，也不留废弃版本文档——细则见 `memory/SKILL.md`。
  - `git-commit` —— 提交规范（Conventional Commits）；来自 `github/awesome-copilot`（MIT）。
  - `skill-creator` —— 写 / 改 skill；来自 `anthropics/skills`（Apache-2.0）。
- 现状：`rules`、`memory` 为自建骨架（备注待补）；`git-commit`、`skill-creator` 为第三方安装。
- **改完 skill 必须重启 opencode 才生效。**

### 记忆的清理机制（硬性）

- **决策文件只写现状态**：一个主题一个文件；新决定**改写同一份**，不新建 `<主题>-2.md`、
  不按日期堆版本。同一件事有多份"旧版本"，读者就得自己比对，等于没有文档。
- **决策文件末尾带一节「变更记录」**，一行一条：**改了什么 / 为什么 / 否掉了什么 / 后果 / Git 哈希**。
  那是**索引**，不是过程——细节看 `git show <hash>`。
- **不记变更流水账**：按日期记"今天改了什么"与 `git log` 重复，必然过期；
  记忆只留**"为什么否掉"与"为什么只能这样"**——这些在代码与历史里找不到，才是记忆存在的理由。
- **没有归档**：过期、被更大变化取代、与事实不符的条目**直接删**，不留"历史文档"让人比对新旧两份。
- **进度文件只记"还没做"**：做完的条目**删掉**，不改 `[x]` 留作历史。
- 每次任务收尾一并清理：过期、已废弃、与代码或文档不符的条目 → **删除或改写**。
  只增不减会腐化失真；记忆必须比代码更短、更新更快。
- 冲突时以路线图、`docs/architecture/*.md` 与代码为准（`路线图 > 设计 > 代码`），记忆服从事实。
