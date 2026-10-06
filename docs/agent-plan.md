# Agent 计划

[返回 README](../README.md) · [进度报告](progress.md) · [项目简介](introduction.md)

把现有的一次性 review 变成：模型自己决定还缺什么信息，调用 CodeGuard 已有的读函数，再写出与现在相同的 findings。

状态：未开始。当前代码没有 tool calling。

## 现在的 review 在做什么

两条入口汇合到同一条 worker：

```text
POST /pull-requests/{id}/review-jobs
  → create_review_job_if_no_active()
  → execute_review_job_task.delay(job_id)
       → execute_review_job_by_id()
            → filter_reviewable_files
            → fetch_github_file_text
            → build_file_windows → pack_review_windows
            → OpenRouterReviewProvider.review_content
            → replace_review_findings
```

`review_content` 向 OpenRouter 的 `/chat/completions` 发一轮 system + user，并要求只返回 JSON。请求里没有 `tools`。Python 在问模型之前已经选定文件、拉完正文、打好窗口。模型不能再要一份文件。

关键文件：

| 文件 | 角色 |
|---|---|
| `backend/app/api/review_jobs.py` | 创建 job，返回 202 |
| `backend/app/tasks/review_jobs.py` | Celery 任务 |
| `backend/app/services/review_jobs.py` | 执行、幂等、`replace_review_findings`、`get_pull_request_for_user` |
| `backend/app/services/github_pr_files.py` | PR 文件同步、`fetch_github_file_text`、`get_pull_request_with_repository` |
| `backend/app/services/diff_chunking.py` | `filter_reviewable_files`、窗口与 pack |
| `backend/app/services/openrouter_provider.py` | 无 tools 的单次 chat，以及 findings 解析 |
| `backend/app/services/review_provider.py` | `ReviewFindingDraft` / `ReviewResult` |

Findings 字段已经固定，前后端都认这套：`severity`（`low` \| `medium` \| `high` \| `critical`）、`summary`、`file_path`、`start_line`、`end_line`、`suggestion`。表是 `review_findings`。Agent 沿用这些字段，不另写一套 schema。

## 原则

1. 先写明白一层循环：模型决定工具，Python 执行，结果交回模型，再决定下一步。框架留到这层能自己跑通之后。
2. 工具是现有 service 的薄包装。Day 2 起不再写第二套 GitHub 客户端。
3. 模型不传入 token，也不传入任意 `owner/repo`。对话入口用当前用户的 `user_id`。Celery 入口从 `review_job_id` → PR → `Repository.user_id` 推出主人，再开现有的 `GitHubTokenSession`。
4. 第一阶段是一个 Review Agent 加多个工具。专家拆分、handoff、换队列都排在后面的天数里。
5. 队列维持 Celery。Day 8 把同一个 runtime 挂进现有 `execute_review_job`。Taskiq 仍只是以后的并发选项，不是开工条件。见 [进度报告](progress.md#worker-并发)。

学习终点是：编排者先计划并取上下文，再按安全、缺陷、性能分头分析，汇总成 findings，经现有 job 写入 Postgres，前端照旧展示。Day 1 不实现这张图。

```text
User
  → Review Request
  → Review Orchestrator
       → Planning + Context Retrieval
       → Security / Bug / Performance
       → Aggregator（去重、按 severity 排序）
  → replace_review_findings
  → 现有前端
```

GitHub 评论写回仍是 Step 9D，暂缓，不绑在某一天的 Agent 任务上。

## Day 1：一个工具，手写循环

目的：让模型自己判断要不要调用 `get_pull_request_info`。学的是调度，不是 GitHub API。

位置：`backend/agent_experiments/agent_day1/`（`tools.py`、`agent.py`、`test_agent.py`）。不进 FastAPI，不进 Celery，不写数据库，不改 `review_content`。

步骤：

1. **Mock 一个工具。** `get_pull_request_info(repo, pr_number)` 固定返回 title、author、files_changed、additions、deletions。传入任何编号都返回同一份假数据。
2. **按 Chat Completions 注册工具。** CodeGuard 打的是 OpenRouter `/chat/completions`，不是 OpenAI Responses API。`strict` 和参数 schema 放在 `function` 里面，`additionalProperties` 为 `false`。系统提示只说明角色：需要 PR 信息时使用提供的工具。提示词里不写调用顺序。
3. **手写循环。** 把 `messages` 和 `tools` 发给模型。`tool_calls` 非空时：原样把 assistant 消息追加回去；`function.arguments` 是 JSON 字符串，先解析再执行 Python 函数；再追加 `role: tool` 的结果。然后再次请求。`tool_calls` 为空时，`content` 就是最终回答。最多 8 轮。
4. **打印整段 trace。** 用户问题、工具名、参数、工具返回值、最终回答。

用现有的 `OPEN_ROUTER_API_KEY` 和 `OPEN_ROUTER_BASE_URL`。模型选 OpenRouter 上标明支持 tools 的一个。当前 review 白名单里的免费模型只服务于「吐 JSON、无 tools」的 `review_content`，Day 1 不走那条函数。若响应里一直没有 `tool_calls`，先打印原始 message，再换模型。

用三个问题看选择会不会变：

| 问题 | 期望 |
|---|---|
| Review PR #42 in mark/codeguard. | 调用 `get_pull_request_info`，再根据返回值回答 |
| Who authored PR #7? | 仍调用该工具，回答只说作者 |
| What is 2 + 2? | 不调用工具 |

成功标准：提示词没有指定工具名，换问题后调用行为变了，终端能看到完整 trace。

Day 1 的 mock 可以暂时用 `repo` + `pr_number`。这个参数形状只存在于实验里。

状态：未开始

## Day 2：三个真工具，输出对齐 findings

目的：同一个循环改为读取当前用户自己的 PR，并在结束时给出 `ReviewFindingDraft`。

代码在 `backend/agent_experiments/agent_day2/`。先打印，不写入 `review_findings`。运行时先绑定 `user_id` 和本地 `pull_request_id`。这两个值由实验脚本传入，不出现在工具 schema 里。

| 工具 | 包装 | 约束 |
|---|---|---|
| `get_pull_request_info` | `get_pull_request_for_user`；需要仓库名时用 `get_pull_request_with_repository` | 返回本地 PR 的 number、title、state、author_login、base_branch、head_branch。模型不能扫任意 owner/repo |
| `get_pull_request_files` | `get_pull_request_files` / `list_PR_files` | 已同步行含 filename、status、additions、deletions、patch、sha、contents_url。PR files 只取第一页（最多 100），与现有同步一致 |
| `get_file_content` | 库里的 `patch`；要全文再 `fetch_github_file_text` | token 走 `GitHubTokenSession`，与 `execute_review_job` 相同。`status == "removed"` 的文件不拉 head |
| `list_reviewable_files`（可选） | `filter_reviewable_files` | 复用现有的 lockfile / 图片 / 生成物忽略规则 |

错误处理放在这一天：未知工具名、参数 JSON 解析失败、工具抛错，都写成一条 `role: tool` 的错误结果交回模型，循环继续，直到轮次上限。

最终回答解析成 `ReviewFindingDraft`。能复用 `OpenRouterReviewProvider` 里现有的 severity 归一和 `_parse_finding`。字段与 `review_content` 的提示词一致。

成功标准：

- 「这个 PR 改了哪些文件」停在文件列表，不把每个文件全文都拉下来。
- 「看认证相关改动」会在文件列表之后读取相关文件，再给出 findings。
- 输出含 severity、summary、file_path、start_line、end_line、suggestion。缺字段时解析失败并记在 trace 里。

状态：未开始

## Day 3：状态、工作记忆、checkpoint

目的：同一轮 review 记住已经拿过的信息，中断后能从已有消息继续。

步骤：

1. 显式 state：已读文件路径、工具结果摘要、当前轮次、绑定的 `pull_request_id` 与 `user_id`。
2. 同一路径的全文不重复拉取，除非这次运行明确要求刷新。
3. `messages` 和 state 可序列化。checkpoint 先落在实验目录的本地 JSON。不新建表。

成功标准：追问「刚才那个登录文件还有没有别的问题」时，state 里已有该文件则直接分析；没有则再调 `get_file_content`。进程停掉后，用同一份 checkpoint 能接着跑。

状态：未开始

## Day 4：按引用继续取代码

目的：变更文件之外，再取读懂这次 diff 所需要的相关代码。

步骤：

1. `get_related_files`：从已读文件的 import / 引用解析出同仓库路径，再交给 `get_file_content`。
2. `search_code`：先在已同步的文件名和 patch 里做文本搜索。
3. 单次工具返回沿用 `REVIEW_PACK_MAX_CHARS` 的量级做截断，结果里写明被截断。全文仍只留在这次运行的内存里，不写库。

向量检索留到文本搜索和 import 跟随不够用的时候再加。Day 4 不引入独立向量库。

成功标准：改 `login` 且该文件引用认证服务时，agent 会继续取那个服务文件。`filter_reviewable_files` 会忽略的 lockfile 不会被拿来当正文。

状态：未开始

## Day 5：Review Planner

目的：先决定审什么、按什么策略审，再进入分析。

步骤：

1. 读取 PR 元数据和变更文件列表。
2. 给每个文件一个处置：`ignore`、`inspect`、`inspect carefully`。忽略规则先复用 `filter_reviewable_files`，planner 只在剩下的文件上排优先级。
3. 写出 review plan：文件、关注点（认证、空值、查询次数等）、还要再取的相关文件。
4. 计划之后才调用 Day 2 / Day 4 的读取工具并生成 findings。

成功标准：一个含 README、lockfile、组件、认证和支付文件的 PR 里，README 与 lockfile 标成 ignore，认证和支付标成 carefully，组件标成 inspect。plan 出现在 trace 里。

状态：未开始

## Day 6：专家作为工具

目的：主 Review Agent 保持最终控制权，把已收集的上下文交给安全、缺陷、性能三个分析函数。

这是 agents as tools：主 agent 决定叫谁，专家返回 findings，不接管后续对话。

三个函数的输入都是已经取到的 diff、源码和仓库约定。返回值仍是 `ReviewFindingDraft` 列表。现有表没有 `category` 列；关注点写进 `summary`，不为此改表。

| 函数 | 关注 |
|---|---|
| 安全 | 认证、授权、注入、密钥、XSS、CSRF、越权 |
| 缺陷 | 空值、边界、错误状态、竞态、逻辑错误 |
| 性能 | N+1、多余请求、过重循环、不必要的重渲染、可缓存点 |

成功标准：认证改动会调用安全分析；热路径或循环会调用性能分析；最终仍是一份 findings，字段与现有表一致。

状态：未开始

## Day 7：Handoff 实验

目的：在同一批 PR 上对比两种编排，并记下 CodeGuard 默认用哪一种。

- **Agents as tools（Day 6）：** 主 agent 全程持有对话和工具。
- **Handoff：** Triage 把任务交给一个专家，由该专家接管后续工具调用，直到它给出 findings。

对比时记录：谁丢了上下文、谁重复读文件、findings 是否仍能解析进 `ReviewFindingDraft`、轮次和耗时。

成功标准：实验笔记写明默认编排。另一种留在 `backend/agent_experiments/`。这一天不改 worker。

状态：未开始

## Day 8：挂进现有 Celery

目的：Day 2 之后稳定下来的那个 runtime 放进现有 review job，外面的队列不变。

```text
POST /pull-requests/{id}/review-jobs
  → RabbitMQ
  → Celery execute_review_job
       → feature flag 关闭：现有 pack + review_content
       → feature flag 打开：Review Agent runtime
            → 工具读 GitHub / Postgres
            → ReviewFindingDraft
            → replace_review_findings
  → 现有前端轮询
```

步骤：

1. Flag 关闭时行为与现在相同。
2. Flag 打开时，worker 只认 `review_job_id`，从 job 推出 PR 和 `Repository.user_id`，再开 `GitHubTokenSession`。
3. 继续用现有的 1 小时 soft limit、整单再跑一次、`create_review_job_if_no_active` 的 active job 幂等。
4. Findings 只通过 `replace_review_findings` 落库。
5. Trace 先写 worker 日志。要给浏览器看进度时，再由执行进程写入 Redis，API 读出来。Job 状态仍是 `pending` → `processing` → `completed` / `failed`。

成功标准：flag 打开后，手动「Run AI review」能跑完一个 job，现有 PR 页能看到 findings。Webhook 仍走旧的 pack 路径，直到这条手动路径稳定。

状态：未开始

## Day 9 及以后：评估和产品化

目的：知道这套 agent 在哪些 PR 上会说错，以及它和现有 pack 路径的成本、延迟差多少。

步骤：

1. 固定一组 PR fixture 和 bad case（漏报、误报、读了不该读的文件、findings 解析失败）。
2. 把 Day 1 的打印换成可查询事件：模型请求、工具名、参数、错误、耗时。10F 那种完整监控仍不做。
3. Guardrails：轮次上限、工具参数越界、输出解析失败时 job 记 `error_message`，不写入半截脏 findings。
4. 记录 token、墙钟时间和 findings 数量，与同一 PR 的 pack 路径对比。
5. 对话 UI 放在「flag 打开时能稳定写出 findings」之后。页面读的仍是 `review_findings`。
6. 评论写回 GitHub 继续算 Step 9D，不放进 Agent 第一版。

状态：未开始

## 对照

| 天 | 交付 | 碰生产代码 |
|---|---|---|
| Day 1 | mock 工具 + 手写循环 + trace | 否 |
| Day 2 | 三个真工具 + `ReviewFindingDraft` | 否，只调用现有 service |
| Day 3 | state 与 checkpoint | 否 |
| Day 4 | import 跟随与文本搜索 | 否 |
| Day 5 | review plan | 否 |
| Day 6 | 安全 / 缺陷 / 性能作为工具 | 否 |
| Day 7 | handoff 对比，选定默认编排 | 否 |
| Day 8 | feature flag 挂进 `execute_review_job` | 是 |
| Day 9+ | fixture、trace、guardrails、成本；然后才是对话 UI | 按需 |

下面这些不出现在 Day 1，各自留在上表对应的那一天：LangChain、LangGraph、OpenAI Agents SDK、多 Agent、向量库、长期记忆、MCP、Planner 框架、webhook 改走 agent、自动 GitHub 评论、把 Celery 换成 Taskiq。
