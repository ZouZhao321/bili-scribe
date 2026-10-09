# Triage 标签

本文件回答一个问题：**一条 issue 或 PR 现在该有哪些标签，由谁来打。** 它是标签名称与组合规则的唯一来源；颜色和说明不在本文件里，由 `gh label clone ZouZhao321/agent-assets -R ZouZhao321/bili-scribe --force` 从来源仓库带入。

## 主线

一条条目从建立到关闭，标签按下面的顺序出现。前四步要人判断，后四步由流程自己维护。

| 阶段 | 该有的标签 | 谁打 |
| --- | --- | --- |
| 新建 | 表单自带的 `labels` | 表单 |
| 还没人评估 | `needs-triage`（表单没带状态角色时才补） | triage workflow |
| 判定可开工 | `ready-for-agent` + 一个 `kind/*` + 一个 `priority/*` | 维护者 |
| 判定要人做 | `ready-for-human` + 一个 `kind/*` + 一个 `priority/*` | 维护者 |
| 等提交者补充 | `needs-info` | 维护者 |
| 还缺维度 | `needs-kind` / `needs-priority` | 每日同步脚本 |
| 长期保留 | `frozen` | 维护者 |
| 长期无活动 | `stale`，再过 7 天自动关闭 | 过期流程 |
| 判定不做 | `wontfix`，按 `not planned` 关闭 | 维护者 |

## 1. 状态角色：这条现在归谁

五个，互斥，同一时刻只留一个；换的时候先摘掉旧的。

| 角色 | 含义 | 可出现的对象 |
| --- | --- | --- |
| `needs-triage` | 还没人评估：类型、优先级、可执行性都未判定 | issue 与 PR |
| `needs-info` | 已评估，缺信息，等提交者回答 | 只 issue |
| `ready-for-agent` | 规格完整（目标、范围、验收标准齐全，不需要人工判断），可交给无人值守的 agent | 只 issue |
| `ready-for-human` | 需要人的判断、凭据或仓库外操作 | 只 issue |
| `wontfix` | 判定不做 | 只 issue |

`needs-triage` 是唯一也会出现在 PR 上的状态角色，由 PR labeler 自动加。

互斥是约定，没有工具强制。唯一有自动化配合的是新 issue：「重构请求」与「工作切片」两个表单自带 `ready-for-agent`，`.github/workflows/triage.yml` 见表单已带状态角色就不再补 `needs-triage`。

状态怎么推进：

| 从 | 到 | 依据 |
| --- | --- | --- |
| `needs-triage` | `ready-for-agent` | 目标、范围、验收标准齐全，不需要人工判断 |
| `needs-triage` | `ready-for-human` | 需要人工判断、凭据或仓库外操作 |
| `needs-triage` | `needs-info` | 缺信息，已向提交者提问 |
| `needs-info` | `needs-triage` 或 `ready-for-*` | 提交者补齐后重新判定 |
| 任意 | `wontfix` | 判定不做 |

## 2. 类型与优先级：这条是什么、多急

两边都是人工判定，各自一次只打一个。

| 标签 | 含义 | 可出现的对象 |
| --- | --- | --- |
| `kind/bug` | 行为与预期不符 | issue 与 PR |
| `kind/feature` | 新能力 | issue 与 PR |
| `kind/refactor` | 行为不变的结构调整 | issue 与 PR |
| `kind/chore` | 依赖、配置、构建、脚本 | issue 与 PR |
| `kind/docs` | 文档 | issue 与 PR |
| `kind/epic` | 需要多个 PR 的大功能，跟踪容器，不对应 PR | 只 issue |
| `priority/critical-urgent` | 阻断发布，立刻处理 | issue 与 PR |
| `priority/important-soon` | 本周期内完成 | issue 与 PR |
| `priority/backlog` | 认可但无排期 | issue 与 PR |

缺 `priority/*` 就是还没评审，不设默认值。三组之间可以自由叠加，`ready-for-agent` + `kind/feature` + `priority/important-soon` 是标准形态。`kind/epic` 不对应 PR，所以也不配 `ready-for-agent` 或 `ready-for-human`。

PR 侧只有 `kind/docs` 与 `kind/chore` 两条路径规则：`.github/workflows/pr-labeler.yml` 调用 `.github/labeler.yml`，改 `**/*.md` 或 `docs/**` 的 PR 得 `kind/docs`，改 `.github/**`、`pyproject.toml`、`uv.lock`、`Dockerfile`、`docker-compose.yml`、`.dockerignore`、`.gitignore`、`script/**` 的得 `kind/chore`，改 `src/` 下源码的不会被自动打上 `kind/*`，这类 PR 的 `kind/*` 由人工补。同一个 PR 可能同时命中两条路径，要人工收敛成一个。

## 3. 缺值标志：还没分类的提示

| 标签 | 含义 | 可出现的对象 |
| --- | --- | --- |
| `needs-kind` | 缺 `kind/*` | 只 issue |
| `needs-priority` | 缺 `priority/*` | 只 issue |

两个都只用于 issue，由 `script/sync-missing-labels.sh` 维护，`.github/workflows/triage.yml` 每天 01:00 UTC 调用一次：没有就打上，有了就摘掉。它跳过带 `frozen` 的条目；内部用 `gh issue list --limit 500`，开启 issue 超过 500 条会截断。

因为是每天跑一次，「刚手工补上 `kind/*`，`needs-kind` 还挂了一天」是正常现象。

## 4. 生命周期与关闭

| 标签 | 含义 | 可出现的对象 |
| --- | --- | --- |
| `frozen` | 不参与过期流程 | issue 与 PR |
| `stale` | 长期无活动的信号，只由过期流程打与摘 | issue 与 PR |

`.github/workflows/stale.yml` 的阈值：issue 60 天无活动打 `stale`、再过 7 天关闭；PR 是 14 天与 7 天。豁免配置里 `exempt-issue-labels` 是 `frozen,kind/epic`，`exempt-pr-labels` 是 `frozen`；被豁免的条目不会被自动关掉，其中 `kind/epic` 是跟踪容器，本来就不该被自动关，所以它不必再加 `frozen`。

`frozen` 与 `stale` 互斥：豁免会拦住新打的 `stale`；对已经带着 `stale` 的条目补上 `frozen` 时，`remove-stale-when-updated` 默认开启，下一次运行会把 `stale` 摘掉。

关闭理由用原生字段：做完用 `completed`，其余用 `not planned`。`not planned` 同时覆盖「判定不做」与「长期无活动自动关闭」两种情况，区分靠标签——带 `wontfix` 的是前者，带 `stale` 的是后者。

## 标签来源与维护

标签名称、颜色与说明以 `ZouZhao321/agent-assets` 为准，本仓库用下面的命令整体带入：

    gh label clone ZouZhao321/agent-assets -R ZouZhao321/bili-scribe --force

`--force` 会用来源仓库的颜色与说明覆盖同名标签；本仓库里多出来的标签不会被删掉。两处定义有冲突时以 `ZouZhao321/agent-assets` 为准，它的集合是 `ZouZhao321/repo-template` 的超集（同名标签的颜色与说明一致），另外还有 `accessibility` 与 `in-progress` 两个标签。

标签改名或增删时同步改三处：本文件、`.github/ISSUE_TEMPLATE/` 里各表单的 `labels` 字段、以及 `ZouZhao321/agent-assets` 上的标签本身（`gh label edit` 改名、`gh label create` 新增），再跑一次上面的命令把颜色与说明带过来。

只用于 issue 的标签不要贴到 PR 上；搜索时写清 `is:issue` 或 `is:pr`。
