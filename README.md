# npu-simulator PR 自动检视

> 📊 **在线报告：<https://komari-koshigaya.github.io/gitcode-npusim-review/report/>**
>
> 🎯 目标仓库：[gitcode.com/cann/npu-simulator/pulls](https://gitcode.com/cann/npu-simulator/pulls)

用 GitHub Actions 每天定时拉取 GitCode `cann/npu-simulator` 的**所有 open PR**，使用「确定性规则 + 可选 LLM」自动进行代码检视，把检视意见提交回 PR，并生成按日期归档的 HTML 日报，通过 **GitHub Pages** 对外展示。

- 🕘 每天北京时间 **凌晨 05:00** 自动运行（也可在 Actions 页手动触发）
- 🤖 规则检视始终运行；配置 LLM 密钥后叠加 AI 检视
- 🔁 **双层去重**：同一提交永不重复评论，即使状态丢失或手动重跑
- 💬 **行内评论**：GitCode 上只把 low/medium/high 的问题挂到对应代码行；完整汇总只写入 HTML 报告，不发汇总评论
- 📅 报告按日期归档在 `report/`，GitHub Pages 自动发布
- 🧪 纯标准库 + 完整单元测试，无需额外运行时依赖

---

## 工作流程

```
GitHub Actions (每天北京时间 05:00)
   │
   ├─ pip install gitcode-cli==0.13.0      # 官方 GitCode CLI（提供 gitcode / gc）
   ├─ gitcode pr list --state open --json  # 拉取所有 open PR
   │
   ├─ 对每个 PR：
   │    ├─ 第一层去重：state/reviews.json 中同 head SHA → 跳过
   │    ├─ 第二层去重：PR 评论里已有对应标记 → 跳过
   │    ├─ gitcode api .../pulls/<n>/files.json → 结构化 diff（含行号）
   │    ├─ 规则检视 +（可选）LLM 检视
   │    └─ gitcode pr review <n> --comment-file <md>  # 提交检视评论
   │
   ├─ 生成 report/YYYY-MM-DD.html + report/index.html
   └─ 提交 report/ 与 state/ 回 main → GitHub Pages 自动重建
```

## 双层去重（重点）

无人值守的任务最怕重复刷评论。本项目用两层机制保证「**已经检视过就跳过**」：

1. **状态层**：`state/reviews.json` 记录每个 PR 最近一次检视的 `head_sha`；
   同一 SHA 再次运行时直接标记「无新提交·跳过」，连 diff 都不会拉取。
2. **评论层**：每次准备评论前，先读取该 PR 已有评论，查找隐藏标记
   `<!-- npu-review sha=<head_sha> -->`；存在就跳过并回填状态。
   这样即使 `state/` 丢失、换了 runner 或手动重跑，也不会重复发送。

只有 **PR 产生了新提交（head SHA 变化）** 才会重新检视并发表评论。
报告里会把「本次已检视」「无新提交·跳过」「已检视过·跳过」「草稿·跳过」「仅报告·未提交」「提交失败」分开标注。

### 提交策略（避免无意义评论）

默认只有出现 **`low` 及以上**（较低 / 中等 / 严重）的**实质问题**时才提交评论；
`info` 级提示（例如“建议补充测试”）以及零发现的 PR **只写入报告、不评论**，
也不落去重状态（下次仍可重新评估）。

并且在 GitCode 上默认**只提交行内评论**（挂在具体代码行），完整的“自动代码检视报告”汇总只保留在
本地 / GitHub Pages 报告里，不单独发汇总评论。需要汇总评论时设 `POST_SUMMARY_COMMENT=1` 或 `--summary-comment`。

可用 `MIN_SEVERITY_TO_POST` / `--min-severity` 调整提交阈值：

- `low`（默认）：只有 low/medium/high 的发现才评论；
- `medium` / `high`：更克制，只对较严重问题评论；
- `info`：info 级提示也评论；
- `any`：即使没有发现也评论（每个 PR 都留痕）。

---

## 快速开始（在自己的仓库部署）

### 1. 配置密钥

必需：

```bash
gh secret set GITCODE_TOKEN -R <owner>/<repo>
# 粘贴你的 GitCode 访问令牌（需要能对目标仓库 PR 发表评论）
```

可选（启用 AI 检视，兼容 OpenAI 风格接口，例如 DeepSeek）：

```bash
gh secret set LLM_API_KEY -R <owner>/<repo>
gh variable set LLM_BASE_URL -R <owner>/<repo> --body "https://api.deepseek.com"
gh variable set LLM_MODEL    -R <owner>/<repo> --body "deepseek-chat"
```

> `LLM_API_KEY` 未配置时，任务仍会运行，仅使用规则检视，报告会注明。
> 工作流也接受名为 **`DS_API_KEY`** 的 Secret（DeepSeek）：优先用 `LLM_API_KEY`，否则回退 `DS_API_KEY`。

获取 GitCode Token：登录 GitCode → 个人设置 → 访问令牌 → 新建（授予仓库 PR / 评论相关权限）。

### 2. 启用 GitHub Pages

仓库 **Settings → Pages → Build and deployment**：

- Source：**Deploy from a branch**
- Branch：**main**，目录：**/ (root)**

仓库根目录已有 `index.html`（跳转到 `report/`）和 `.nojekyll`，因此启用后即可访问：

- 报告首页：`https://<owner>.github.io/<repo>/report/`
- 裸仓库地址：`https://<owner>.github.io/<repo>/`（自动跳转）

### 3. 运行

- 自动：每天北京时间 **凌晨 05:00** 执行。
- 手动：Actions → **GitCode PR Review** → **Run workflow**
  - 勾选 `dry_run` 则只生成报告、不提交评论（报告以 artifact 形式上传，不写入仓库）。

首次运行会创建当天报告并提交回 `main`，Pages 随即更新。

---

## 本地运行

```bash
# 1. 安装官方 GitCode CLI（提供 gitcode / gc 命令）
pip install gitcode-cli==0.13.0

# 2. 设置令牌
export GITCODE_TOKEN=你的令牌          # Windows: $env:GITCODE_TOKEN="..."

# 3. 预览：只生成报告，不提交评论
python -m reviewer --dry-run --report-dir _preview

# 4. 正式运行：检视并提交评论
python -m reviewer
```

### 离线演示（无需网络 / 令牌）

仓库内置夹具，可完整跑通「解析 → 检视 → 生成报告」流程：

```bash
python -m reviewer --offline-fixture tests/fixtures/offline_run.json --report-dir _preview
```

`_preview/` 下会生成 `YYYY-MM-DD.html`、`index.html`、`runs.json`，直接用浏览器打开即可。

### 运行测试

```bash
pip install pytest
python -m pytest -q
```

---

## 命令与配置

### 命令行参数

| 参数 | 说明 |
| --- | --- |
| `--repo owner/repo` | 目标仓库，默认 `cann/npu-simulator` |
| `--report-dir DIR` | 报告目录，默认 `report` |
| `--state-file FILE` | 状态文件，默认 `state/reviews.json` |
| `--dry-run` | 只生成报告，不提交评论 |
| `--force-review` | 忽略去重，强制重新检视并评论（人工兜底） |
| `--max-prs N` | 本次最多处理 N 个 PR（0 使用默认值） |
| `--min-severity LEVEL` | 达到该严重度才提交评论：`any/high/medium/low/info`，默认 `low` |
| `--no-inline-comments` | 只发汇总评论，不发代码行内评论 |
| `--max-inline-comments N` | 每个 PR 最多 N 条行内评论（默认 3） |
| `--summary-comment` | 额外提交一条汇总评论（默认不发，汇总只写报告） |
| `--include-drafts` | 连草稿 PR 一起检视 |
| `--offline-fixture FILE` | 使用离线夹具运行（自动 dry-run） |
| `--version` | 打印版本 |

### 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `GITCODE_TOKEN` / `GC_TOKEN` | — | GitCode 访问令牌（必需） |
| `GITCODE_REPO` | `cann/npu-simulator` | 目标仓库 |
| `GITCODE_BIN` | 自动查找 | `gitcode`/`gc` 可执行文件路径 |
| `DRY_RUN` | `false` | 同 `--dry-run` |
| `INCLUDE_DRAFTS` | `false` | 是否检视草稿 PR |
| `MAX_PRS` | `100` | 单次最多处理 PR 数 |
| `REPORT_TZ_OFFSET_HOURS` | `8` | 报告时区（北京 +8） |
| `LARGE_FILE_LINES` | `800` | 单文件改动行数告警阈值 |
| `LONG_LINE_CHARS` | `200` | 新增行长度告警阈值 |
| `MAX_FINDINGS_IN_COMMENT` | `30` | 单条评论最多展开的发现数 |
| `MIN_SEVERITY_TO_POST` | `low` | 最高严重度达到该级别才提交评论（`info` 级只记录；`any` 表示总是提交） |
| `INLINE_COMMENTS` | `true` | 是否提交代码行内评论 |
| `MAX_INLINE_COMMENTS` | `3` | 每个 PR 行内评论上限 |
| `POST_SUMMARY_COMMENT` | `false` | 是否额外提交汇总评论（默认只发行内，汇总只写报告） |
| `LLM_API_KEY` | 空 | 配置后启用 AI 检视 |
| `LLM_BASE_URL` | `https://api.deepseek.com` | OpenAI 风格接口地址 |
| `LLM_MODEL` | `deepseek-chat` | 模型名 |
| `LLM_TIMEOUT` | `120` | 请求超时（秒） |
| `LLM_MAX_DIFF_CHARS` | `60000` | 送入模型的 diff 上限 |
| `LLM_MAX_PRS` | `20` | 单次最多对多少个 PR 调用 LLM（控制成本） |

### 规则检视覆盖

| 规则 | 严重度 | 说明 |
| --- | --- | --- |
| `hardcoded-secret` | 严重 | 疑似硬编码密钥 / 口令 / Token |
| `merge-conflict` | 严重 | 残留 `<<<<<<<` / `=======` / `>>>>>>>` |
| `swallowed-exception` | 中等 | `except: pass` 吞异常 |
| `empty-catch` | 中等 | 空 `catch {}` |
| `debug-print` | 较低 | `print` / `printf` / `console.log` / `fmt.Print` / `std::cout` 等 |
| `long-line` | 较低 | 新增行超长 |
| `todo-marker` | 提示 | `TODO` / `FIXME` / `HACK` / `XXX` |
| `deleted-file` | 提示 | 删除文件 |
| `large-change` | 提示 | 单文件改动过大 |
| `missing-tests` | 提示 | 改了代码但没改测试 |

> - 生成物 / 锁文件（如 `package-lock.json`、`*.min.js`、`go.sum`）会跳过低价值检查。
> - 文档（`.md` / `.rst` / `.txt`）不检查行长；`missing-tests` 只针对源码文件（`.c/.cpp/.py/.go/...`），
>   避免对纯文档 / CI 改动产生噪声。

LLM 检视的发现会以 `engine=llm` 单独标注；AI 调用失败时自动降级为仅规则，**不会让整次任务失败**。

---

## 报告与页面

- `report/YYYY-MM-DD.html`：当天日报，包含
  - 概览卡片（open PR 数 / 本次检视 / 已提交意见 / 跳过 / 失败 / 发现总数）
  - 所有 open PR 一览表（编号、标题、作者、分支、状态、风险、发现数）
  - 每个已检视 PR 的发现明细与「提交到 GitCode 的评论原文」
- `report/index.html`：历史报告索引，按日期倒序
- `report/runs.json`：每次运行的摘要数据（供索引页渲染）

所有动态文本都经过 HTML 转义，避免 PR 标题 / diff 内容造成 XSS。

---

## 目录结构

```
.github/workflows/review.yml   # 每日检视任务
.github/workflows/ci.yml       # 单元测试
reviewer/
  cli.py                       # 主流程编排 / 命令行入口
  config.py                    # 配置（env + 参数）
  gitcode.py                   # 对 gitcode CLI 的封装
  diffparser.py                # PR diff 解析（结构化 API + 文本回退）
  state.py                     # 去重状态
  comment.py                   # 评论 Markdown 与隐藏标记
  report.py                    # HTML 日报与索引
  engine/rules.py              # 规则检视
  engine/llm.py                # LLM 检视（OpenAI 兼容，失败降级）
tests/                         # pytest 单元测试与夹具
report/                        # 生成的报告（提交回仓库，由 Pages 展示）
state/                         # 去重状态（提交回仓库）
```

---

## 说明与边界

- **关于 `atomgit`**：`pip install atomgit` 安装的是「模型 / 数据集上传下载」CLI，**不支持 PR 操作**。
  本项目实际使用的是官方 **`gitcode-cli`**（安装后提供 `gitcode` / `gc` 命令）。
- **评论权限**：`GITCODE_TOKEN` 的用户需要能对目标仓库 PR 发表评论；若令牌属主恰好是 PR 作者，
  个别平台可能拒绝，失败会记录在报告里而不会中断整次运行。
- **只评论，不审批**：本项目只提交普通检视评论（`pr review --comment`），
  不 `approve`、不 `request changes`，不会阻塞合并。
- **定时任务**：GitHub 的 `schedule` 在公开仓库长期无活动后可能被自动停用，
  可随时在 Actions 页手动 `Run workflow`；定时任务仅在默认分支生效。
- **成本控制**：LLM 检视受 `LLM_MAX_PRS` 与 `LLM_MAX_DIFF_CHARS` 限制；
  规则检视对全部 PR 运行。

## License

[MIT](./LICENSE)
