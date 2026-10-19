# Agent 计划

[返回 README](../README.md) · [进度报告](progress.md) · [项目简介](introduction.md)

把现有的一次性 review 变成：模型自己决定还缺什么信息，调用 CodeGuard 已有的读函数，再写出与现在相同的 findings。

状态：Day 1–6 的实验已经跑通。产品 review 仍是下面这条没有 tools 的 pack 路径。Day 7 不实现。下一步是把 Day 6 同一轮里的读文件和专家调用改成并行，然后进入 Day 8。

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

1. 先写明白一层循环：模型决定工具，Python 执行，结果交回模型，再决定下一步。LangChain、LangGraph、Agents SDK 要学，也要在实验里对照实现，但放在 Day 8 的手写 runtime 进 Celery 之后，不替换这条主线。
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

状态：实验已跑通。产品路径未改。

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

状态：实验已跑通。产品路径未改。

## Day 3：状态、工作记忆、checkpoint

目的：同一轮 review 记住已经拿过的信息，中断后能从已有消息继续。

步骤：

1. 显式 state：已读文件路径、工具结果摘要、当前轮次、绑定的 `pull_request_id` 与 `user_id`。
2. 同一路径的全文不重复拉取，除非这次运行明确要求刷新。
3. `messages` 和 state 可序列化。checkpoint 先落在实验目录的本地 JSON。不新建表。
4. `get_file_content` 与 `refresh_file_content` 的说明写清何时调用。模型自己选工具。执行器不根据用户句子接受或拒绝刷新。

成功标准：追问「刚才那个登录文件还有没有别的问题」时，state 里已有该文件则直接分析；没有则再调 `get_file_content`。进程停掉后，用同一份 checkpoint 能接着跑。

状态：实验已跑通。产品路径未改。

## Day 4：按引用继续取代码

目的：变更文件之外，再取读懂这次 diff 所需要的相关代码。

步骤：

1. `get_related_files`：从已读文件的 import / 引用解析出同仓库路径，再交给 `get_file_content`。
2. `search_code`：先在已同步的文件名和 patch 里做文本搜索。
3. 单次工具返回沿用 `REVIEW_PACK_MAX_CHARS` 的量级做截断，结果里写明被截断。全文仍只留在这次运行的内存里，不写库。

向量库不在 Day 4–9。Day 9 的 bad case 若经常是「import 和文本搜索都找不到、但语义上相关的文件」，再在 Day 9 之后引入。Day 4 不建向量库。

成功标准：改 `login` 且该文件引用认证服务时，agent 会继续取那个服务文件。`filter_reviewable_files` 会忽略的 lockfile 不会被拿来当正文。

状态：实验已跑通。产品路径未改。

## Day 5：Review Planner

位置：`backend/agent_experiments/agent_day5/`。实验仍调用 Day 4 的 `get_file_content`，还不改成生产里的 hunk 窗口打包。

目的：先决定审什么、按什么策略审，再进入分析。

步骤：

1. 读取 PR 元数据和变更文件列表。
2. 给每个文件一个处置：`ignore`、`inspect`、`inspect carefully`。忽略规则先复用 `filter_reviewable_files`，planner 只在剩下的文件上排优先级。
3. 写出 review plan：文件、关注点（认证、空值、查询次数等）、还要再取的相关文件。
4. 计划之后才调用 Day 2 / Day 4 的读取工具并生成 findings。

成功标准：一个含 README、lockfile、组件、认证和支付文件的 PR 里，README 与 lockfile 标成 ignore，认证和支付标成 carefully，组件标成 inspect。plan 出现在 trace 里。

状态：实验已跑通。PR #31 上 README 与文档为 ignore，代码为 inspect；该 PR 没有认证或支付文件，所以没有出现 inspect_carefully。产品路径未改。

## Day 6：多 Agent 协作（编排者调用专家）

位置：`backend/agent_experiments/agent_day6/`。编排者沿用 Day 5 的计划和读取。专家没有读文件工具。

目的：同一次 review 里有多个 Agent。编排者决定叫谁，专家各自审查自己的那一片上下文，汇总只合并他们已经写出的 findings。

这是 agents as tools。每一次专家调用都是一次独立的模型对话，不是编排者自己把各个角度写完。

角色：

| Agent | 做什么 | 不做什么 |
|---|---|---|
| 编排者 | 读 Day 5 的 plan，再按风险把已读文件派给一位或多位专家 | 不自己产出最终 findings。不把 GitHub token 交给专家 |
| 安全专家 | 认证、授权、注入、XSS、CSRF、SSRF、路径穿越、密钥、加密、敏感数据暴露 | 不能调用读文件工具，不能扩大范围 |
| 正确性专家 | 逻辑、空值、错误处理、状态、并发、边界 | 同上 |
| 性能专家 | N+1、无界读取、热路径阻塞、重复的昂贵调用 | 同上 |
| 可靠性专家 | 超时、重试、幂等、部分失败、事务、资源泄漏 | 同上 |
| 契约专家 | API 形状、校验、迁移、事件和已存数据的兼容 | 同上 |
| 变更风险专家 | 只改了一处的重复规则、与行为矛盾的命名或分支 | 不报格式和命名偏好 |
| 汇总 | 同一文件、同一行、同一问题的多条合成一条，按 severity 排序 | 不新增专家没写过的问题。汇总是代码，不再叫一次模型 |

每个专家有自己的 system prompt 和自己的 `messages`。输入是编排者点名的已读文件，不是整段编排对话。输出仍是 `ReviewFindingDraft`。现有表没有 `category` 列；关注点写进 `summary`。

成功标准：认证或外部输入至少叫到安全专家；查询循环或热路径至少叫到性能专家。trace 里能看到编排者的分发、每一家专家的单独回复、以及汇总后的一份 findings。专家没被分到的文件不出现在它的输入里。

状态：实验已跑通。PR #31 上叫到安全、正确性、性能、可靠性；契约和变更风险未叫。汇总出 14 条 findings。正确性与可靠性对 Day 1 过窄 `except` 的两条相近 finding 没有合成。同一轮里的读文件和专家调用已改为并行；模型若仍每轮只发一个调用，等待时间不会下降。产品路径未改。

## Day 7：换一种协作（handoff）

位置：`backend/agent_experiments/agent_day7/`。只做实验，不改 Celery worker。

目的：Day 6 是编排者始终拿着对话和读文件工具，专家只交回 findings。这一天实验另一种协作：分诊之后，把后续轮次整个交给一个专家。

- **Day 6：** 编排者调用专家，专家只返回 findings，然后回到编排者。
- **Handoff：** 分诊 Agent 选定一个专家后，该专家接管工具调用和后续轮次，直到它写出 findings。编排者不再插嘴。

实现时分诊仍先交出 Day 5 的 plan，并选定一位专家和起始路径。之后 Python 换成该专家的 system prompt 和一份新的 `messages`，工具仍是现有的读文件工具。`user_id` 和 `pull_request_id` 继续由 Python 绑定，模型不能自己传 token 或仓库。专家循环直到写出可解析的 findings，或用完轮次。

同一个 PR 再留一份 Day 6 的结果。笔记记下谁丢了上下文、谁重复读文件、findings 能否解析、轮次和耗时。

成功标准：笔记写明 CodeGuard 默认用 Day 6。Handoff 留在 `backend/agent_experiments/`。默认用 Day 6，是因为读文件的权限必须留在绑定了 `user_id` 和 `pull_request_id` 的运行时手里，不把 token 放进模型可见的参数。这一天不改 worker。

状态：不实现。流程留在本节作对照。产品默认 Day 6：一次审核要同时覆盖多个风险，读文件权留在编排者手里。Handoff 只剩一个专家视角，不适合作为默认。

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

## Day 9：评估、观测和上下文

目的：知道这套 agent 在哪些 PR 上会说错，以及它和现有 pack 路径的成本、延迟差多少。Day 9 之后的微调和向量库都用这里留下的记录。

步骤：

1. 固定一组 PR fixture 和 bad case：漏报、误报、该调的工具没调、读了不该读的文件、findings 解析失败。每条记下期望的工具序列。
2. 指标至少包括：任务是否完成、工具选择是否正确、参数是否正确、延迟、token 数。和同一 PR 的 pack 路径对比。
3. 把 Day 1 的打印换成可查询事件：模型请求、工具名、参数、错误、耗时。事件先写 worker 日志；要按请求串起来时，用 OpenTelemetry 的 trace / span 打在 FastAPI 和这次 agent 调用上。10F 那种完整监控仍不做。
4. Guardrails：轮次上限、工具参数越界、输出解析失败时 job 记 `error_message`，不写入半截脏 findings。
5. 对话变长时做一次压缩实验：留下系统提示、当前任务、已读路径摘要和最近几轮，不把每一份全文永远堆在 `messages` 里。压缩前后各跑同一条 fixture。
6. 对话 UI 放在「flag 打开时能稳定写出 findings」之后。页面读的仍是 `review_findings`。
7. 评论写回 GitHub 继续算 Step 9D，不放进这一天。

状态：未开始

## Day 9 之后：必须学到的技术

Day 5–9 继续用手写循环和现成 OpenRouter 模型，数据库仍是 Postgres。下面这些要做进实验，不替换 Celery 主线，也不另开电商 demo。多 Agent 本身在 Day 6 和 Day 7。

顺序：

1. **混合检索。** 用 Day 9 里「import 和文本搜索都找不到相关文件」的 bad case 作为查询集。先做一层 BM25，再加稠密向量，用 Qdrant 做 hybrid query，然后 rerank，只把前几名交给 `search_code` 的调用方。算 Recall@K。索引的是仓库代码，不是把 review 全文再存进业务库。Lockfile、图片和已读文件仍然丢掉。
2. **工具太多时的检索。** 工具 schema 多到十几二十个、模型经常选错时，先选出和这句话相关的几个 schema，再交给主模型。这和上一条选源码不是同一件事。
3. **LangChain 与 LangGraph。** 用 LangChain 把现有读工具包成 `@tool`，用 LangGraph 把 Day 3 的 state、循环和 checkpoint 重写成一张图，对照手写 runtime 和 Day 8 的 Celery 入口。实验放在 `backend/agent_experiments/`，生产依赖不加入 LangChain。同时用 OpenAI Agents SDK 做一版同样的 review loop，写下框架多管了 agent loop、state 和 handoff 里的哪几项。
4. **QLoRA / SFT，然后 DPO。** 用 Day 9 修正过的 findings 和正确的 tool call 轨迹，在开放权重模型上做 SFT。样本先积累到数百条。格式稳定后，把采纳的 finding 和误报配成偏好对做 DPO。PPO 那种完整 RLHF 只记录为什么贵、为什么不做。免费 OpenRouter 模型没有可训练权重，这一步要换基座或使用厂商的 fine-tuning 接口。
5. **MCP。** 把 Day 2–4 的只读工具包成 MCP Server，让另一个 Host 调用。写 GitHub 仍是 Step 9D。
6. **记忆分层。** 短对话状态放 Redis，可恢复的 `messages`、已读路径和 job 状态留在 Postgres。语义记忆就是上面的向量索引，不另做第三套用户档案。
7. **产品面。** 同一 runtime 上做：对着一个 PR 提问、变更摘要、finding 分诊、影响面。安全聚焦已经在 Day 6。自动改代码、自己开 PR 不做。
8. **面试用的系统设计与算法。** 不改产品技术栈。用现有 Postgres 讲清索引、事务和并发；用现有 Redis 讲清缓存击穿和一致性；用现有 RabbitMQ / Celery 讲清 ack、重试、重复投递和 active job 幂等。另外单独练系统设计题和算法题，不阻塞 Day 5。

明确不采纳：用商品搜索和优惠券替换 CodeGuard 的工具；把数据库改成 MySQL；在 Day 5 之前用框架重写循环；在 Day 4 就上向量库；为了面试重做一条队列。

状态：未排期

## 对照

| 天 | 交付 | 碰生产代码 |
|---|---|---|
| Day 1 | mock 工具 + 手写循环 + trace | 否。实验已跑通 |
| Day 2 | 三个真工具 + `ReviewFindingDraft` | 否。实验已跑通 |
| Day 3 | state 与 checkpoint | 否。实验已跑通 |
| Day 4 | import 跟随与文本搜索 | 否。实验已跑通 |
| Day 5 | review plan | 否。实验已跑通 |
| Day 6 | 编排者、六位专家、代码汇总协作 | 否。实验已跑通 |
| Day 7 | handoff 流程仅作对照，不实现 | 否 |
| Day 8 | feature flag 挂进 `execute_review_job` | 是 |
| Day 9 | fixture、指标、OpenTelemetry、上下文压缩 | 按需 |
| Day 9 之后 | Qdrant 混合检索与 rerank、工具检索、LangChain / LangGraph / Agents SDK、SFT、DPO、MCP、记忆分层、Ask / 分诊 | 实验目录。主线仍是 Celery |

Day 1 不做 LangChain、LangGraph、Agents SDK、向量库、长期记忆、MCP、自动 GitHub 评论，也不换 Taskiq。多 Agent 用 Day 6。Day 7 的 handoff 不实现。框架、混合检索和微调在 Day 9 之后，都要做进实验。
