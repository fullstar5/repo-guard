# 进度报告

[返回 README](../README.md) · [项目简介](introduction.md) · [Agent 计划](agent-plan.md) · [测试与本地命令](testing.md)

## 状态

已完成 GitHub 集成、结构化 AI review、异步任务、前端展示、webhook 自动 review、delivery / active job 两层幂等，以及 Vercel + Northflank + CloudAMQP 的 0 成本部署。手动 review 可选白名单模型。9D 评论暂缓。10F 跳过。11A 打包与 1 小时整单重试已落地。11A-3 取消。

合入 `main` 后 GitHub Actions 推 GHCR，API / worker 跟 `:main`。改表则本地先对生产 Neon 跑迁移再合入。上线 worker 必须带上超时和 packing 环境变量，以及 `--without-gossip --without-mingle --without-heartbeat`。

生产上手动 review 与 webhook Redeliver 已通。对已 sync 仓库 `git push` 后是否自动出现 review job，仍待补测。对象级读隔离已有自动化测试锁住。UI 仍是功能向 MVP。

| 范围 | 状态 |
|---|---|
| Step 1–8 | 已完成。展示层是 MVP |
| Step 9A–9C | 已完成。9D 评论写回暂缓 |
| Step 10A–10E | 已完成。10F 可观测性跳过。10G 是隔离的 GCP 练习，不是产品路径 |
| Step 11A-1 / 11A-2 / 11A-4 / 11A-5 | 已落地 |
| Step 11A-3 | 取消。单 pack 预算远小于 128k 级窗口，不再把超限响应拆成更小请求 |
| Step 11 其余 | 安全加固、UI、模型质量未开始。打包 / review / webhook / 展示层关键路径已有自动化测试 |
| 自动化测试 | 后端 125、前端 30。CI 跑 `pytest -q` 与 `npm test`。生产 push、浏览器登录、severity 过滤未覆盖 |
| 模型选择 | PR 页可选白名单。Webhook 仍用 `OPEN_ROUTER_DEFAULT_MODEL` |
| Worker 并发 | 继续 Celery prefork。Agent 不以此为开工条件 |
| Agent | 未开始。当前 `review_content` 无 tools。按天计划在 [Agent 计划](agent-plan.md) |

### 自动化测试

状态：核心路径已有 mock 测试。不连 GitHub、OpenRouter、Postgres 或 Redis。逐条用例和本地命令在 [测试与本地命令](testing.md)。

已完成：

- 后端 `cd backend && pytest -q`：**125** 个，在 `backend/test/`。覆盖打包与窗口、GitHub 文件正文、仓库和 PR 的 `Link` 分页、同步落库、review 执行（小 PR、大 PR、部分 pack 失败仍 `completed`、全部失败、去重与 `file_path`）、任务重试与 reclaim、OAuth / JWT、GitHub token 轮换与 401 后刷新、webhook 幂等和自动 review 流水线、HTTP sync / review、非属主 404 与查询绑定 `user_id`、限流、健康检查、OpenRouter 解析。
- 前端 `cd frontend && npm test`（Vitest，jsdom）：**30** 个，在 `frontend/test/`。覆盖 Option A 钉选与 latest、无效 `jobId` 不展示别的 findings、Run AI review、API client、Sync 按钮，以及 sync 后用 POST 结果替换 query cache。没有浏览器 E2E。
- CI：backend job 跑 `pytest -q`；frontend job 在 `tsc` 之后、`npm run build` 之前跑 `npm test`。

仍开着的测试缺口：

- 生产环境对已 sync 仓库 `git push` 后，webhook 是否自动创建并完成 review job（手工，未做）
- compose 启动、curl、浏览器里的完整 GitHub 登录
- 展示层按 severity 过滤 findings
- PR files 的 `Link` 分页还没做；现有测试锁的是「只取第一页」
- Webhook pipeline 的任务级重试，以及同一 `pending` job 被多个 worker 同时消费，实现和测试都还没有

## 下一步

1. 失败 pack 再审一轮，仍有缺口则 job 标 `partial`（尚未做）
2. 补测：对已 sync 仓库 `git push` 后，生产 webhook 是否自动创建并完成 review job（仍是手工）
3. Step 11 其余：安全加固（token 加密、GitHub ACL 复检等）、UI polish、模型质量。读接口的非属主 404 已有自动化测试
4. Step 9D（可选、暂缓）：findings 写回 GitHub PR 评论
5. Agent：按 [Agent 计划](agent-plan.md) 从 Day 1 实验开始。Day 8 才用 feature flag 挂进现有 Celery job。现在不改队列，也不把开工定义成迁移 Taskiq

### Worker 并发

已决定，先不改。当前 worker 继续用 Celery prefork。`--concurrency` 是子进程个数；每个子进程领一个 job，等 OpenRouter 时不领下一个。账号大约 20 RPM，同时两三个 job 就够，不为此自写消费者。

不采用「aio-pika 解析 Celery 消息」：重试、软超时和定时回收都要重写，消息格式却还是 Celery 的。

先前把「Agent 开工」写成换 Taskiq（RabbitMQ 用 `taskiq-aio-pika`，仍走现有 CloudAMQP）：任务是 `async def`，一个进程里可以同时挂多条模型连接，并单独取消其中一轮。这个并发选项保留，但不是 Agent 的开工条件。Day 1–7 只在 `backend/agent_experiments/` 里跑；Day 8 把同一个 runtime 挂进现有 `execute_review_job`。Streaming 不改数据路径：打开模型 HTTP 的那个进程把工具事件写入 Redis，API 读出来给浏览器。现有 Celery 子进程也能写 Redis。顺序见 [Agent 计划](agent-plan.md)。

FastStream 只做异步消费者，重试和定时回收要自己写。gevent 与当前异步数据库引擎冲突。ARQ 需要真正的 Redis 连接，Upstash REST 不行。Temporal 要多一个服务。这几项不采用。

## 路线图

每一步对应一个工程目标。下面按步骤保留实现记录。

### Step 1: 项目初始化

目的：建立可持续迭代的项目骨架。

- 初始化 monorepo
- 建立 `frontend/` 和 `backend/` 基础目录
- 补充根目录 `README`、后续文档和基础规范

状态：已完成

### Step 2: Backend 基础设施

目的：先打通后端基础依赖，让服务具备最小可运行能力。

- 搭建 FastAPI 应用
- 连接 Neon PostgreSQL
- 连接 Upstash Redis
- 建立 `/health` 健康检查
- 建立 SQLAlchemy + Alembic 基础迁移能力

状态：已完成

### Step 3: GitHub 身份与数据同步

目的：把 GitHub 用户、仓库、PR 数据同步进本地系统。

- GitHub 登录
- 用户落库
- JWT 认证与 `/auth/me`
- 同步 repositories
- 同步 pull requests
- 同步 pull request files / patch

状态：已完成

### Step 4: AI Review 输入准备

目的：把 PR diff 转换为模型可消费的输入。

- 建立 `review_jobs` 数据模型
- 建立 diff chunking 逻辑
- 支持小 PR 单请求 review
- 支持大 PR fallback chunking

状态：已完成（运行时路径已由 Step 11A 的窗口打包取代）

### Step 5: AI Review v1

目的：先把一版可运行的 AI review 链路跑通。

- 抽象 review provider 接口
- 接入 OpenRouter 在线模型
- 基于 `review_jobs` 执行同步 review
- 将 review summary 回写数据库

状态：已完成基础版本

### Step 6: 结构化 Review Findings

目的：把大段文本 review 结果升级为可展示、可定位、可扩展的数据结构。

- 增加 findings 数据表
- 保存 severity、summary、file_path、line range、suggestion
- 让模型输出结构化结果，而不只是纯文本 summary

状态：已完成基础版本

### Step 7: 异步任务系统

目的：把 AI review 从同步接口调用升级为真正后台执行。

- 引入 RabbitMQ
- 引入 Celery Worker
- 将 review job 提交到队列
- 支持任务状态轮询、失败重试和错误记录

#### Phase 7A: RabbitMQ + Celery 最小消息流

目标：先打通消息队列和 worker，不急着修改现有 review API。

- 启动 RabbitMQ
- 创建 Celery app
- 编写一个最小任务（如 `hello` / `add`）
- 启动 worker 并验证 `delay()` 后任务能够被消费

状态：已完成

#### Phase 7B: Celery 接入 review job 执行逻辑

目标：让 Celery worker 真正调用 `execute_review_job()`。

- 定义 review job task
- task 接收 `review_job_id`
- worker 在后台执行 review
- 结果继续写回 `review_jobs` / `review_findings`

状态：已完成

#### Phase 7C: API 改造为异步任务接口

目标：把创建 review job 的接口改成真正的异步接口。

- `POST /pull-requests/{id}/review-jobs` 只负责创建 job
- job 初始状态写为 `pending`
- API 将任务发送到 RabbitMQ
- 立即返回 `202 Accepted`

状态：已完成

#### Phase 7D: 状态轮询与查询规范

目标：让客户端可以通过 job 查询接口获取最新状态。

- 明确状态流转：`pending -> processing -> completed / failed`
- 基于 `GET /review-jobs/{id}` 查询状态
- 为前端轮询和后续展示层打基础

状态：已完成

#### Phase 7E: 可靠性与工程化补全

目标：把异步系统从“能跑”升级到“更接近真实工程”。

- 增加任务级重试（瞬时 HTTP/网络错误 + 指数退避）
- 增加超时控制（soft/hard time limit；review 任务 1 小时掐断后整单再跑一次）
- 增加日志和错误记录（worker 写回 `review_jobs.error_message`）
- 终态 job 幂等跳过，避免 at-least-once 重复执行
- Celery Beat 自动回收 stale `processing` jobs（本地每 6 小时；按每个 job 的 `updated_at`）
- 本地 `compose.yaml`：api + worker + beat + rabbitmq
- task 层失败路径自动化测试（第一次 soft timeout 整单重试 / 第二次写 `failed` / 重试耗尽 / reclaim）

状态：已完成

Step 7 总状态：已完成 Phase 7A–7E

### Step 8: Review 展示层

目的：让 review 结果真正可被用户消费。

- 前端 GitHub 登录与 session
- 展示 repositories / PRs / files
- 触发 review job，并轮询 `pending / processing / completed / failed`
- 展示 review findings
- 按文件和严重级别过滤
- 提供类似 GitHub review 的阅读体验

#### Phase 8A: 前端基础与登录

- 后端补 CORS，允许 `frontend_url`
- 打通 GitHub OAuth 回跳到前端并保存 access token
- 建立 API client（axios + TanStack Query）
- 登录页 / 当前用户信息

状态：已完成

#### Phase 8B: Repo / PR 浏览

- 后端补 `GET` 列表接口（当前只有 sync `POST`）
- 前端仓库列表、PR 列表
- 手动 sync 按钮（复用现有 sync API）

状态：已完成

#### Phase 8C: 异步 Review 触发与状态

- 在 PR 详情触发 review job
- 轮询 job 状态
- 展示 `pending / processing / completed / failed` 和 `error_message`

状态：已完成

#### Phase 8D: Findings 阅读体验

- 展示 `result_summary` 与 findings 列表
- 按 `file_path`、`severity` 过滤
- 定位到文件和行号（接近 GitHub review 的阅读方式）

状态：已完成（MVP：点 job 查看 findings，点 finding 进入文件 diff 并滚到行号。左右分栏、行内发评论等产品深度见 Step 11）

Step 8 总状态：已完成 Phase 8A–8D。展示层功能闭环已通，视觉与安全工程化补强见 Step 11。

### Step 9: GitHub Event-Driven Automation

目的：把 CodeGuard 从「用户主动点 Sync / Run AI review」升级为由 GitHub Pull Request 事件驱动的异步 review 系统。

原则：不重构已经工作的 AI pipeline（Step 3–7 的 sync / `create_review_job` / Celery / OpenRouter）。Webhook 只接到这条链前面。

身份约束（第一轮不做 GitHub App）：

- 现有模型是 GitHub OAuth 用户 token，仓库挂在 `repositories.user_id` 上
- Webhook 没有 JWT / `current_user`
- 用 `payload.repository.id` → `repositories.github_repo_id` → owner 的 OAuth token
- 本地还没有该仓库则记日志并跳过，不在 webhook 里给陌生人建用户

开发环境公网入口（ngrok / Cloudflare Tunnel）只是把 `localhost` 暴露给 GitHub 的工具，不是正式架构组件，不要写进业务代码。生产入口属于 Step 10。

状态：9A / 9B / 9C 已完成。9D 暂缓。生产入口已在 Step 10C/10D 落地。

#### Phase 9A: GitHub Webhook（验签 + 过滤，不跑 AI）

目标：GitHub 能把事件送到 CodeGuard，并证明请求真的来自 GitHub。

- 增加 `POST /webhooks/github`（不要 `Depends(get_current_user)`）
- 配置 `GITHUB_WEBHOOK_SECRET`；开发时用隧道提供公网 URL
- 用原始 request body 校验 `X-Hub-Signature-256`（HMAC SHA-256）；失败返回 401/403
- 只关心 `X-GitHub-Event: pull_request`，第一阶段只入队处理 `opened` 和 `synchronize`
- 记录 `X-GitHub-Delivery`、event type、action；马上返回 2xx
- `ping` 以及未支持的 action：仍返回 2xx + 打日志，不当 4xx（否则 GitHub 设置页显示投递失败）

Webhook 不执行 AI、不等待 Celery、不调用 OpenRouter。它只做：Verify → Validate →（9B 起才 Dispatch）→ Return。

状态：已完成（ngrok 公网 URL + HMAC；`ping` / `opened` / `synchronize` 返回 2xx；`handled` 仅对 `opened`/`synchronize` 为 true）

#### Phase 9B: 自动 Review Pipeline

目标：复用 Step 3–7，把 webhook 接到现有 sync 和 review job。不要再写第二套 webhook-only review service。

```text
GitHub pull_request
  → HMAC
  → 按 github_repo_id 找本地 repository
  → 取 owner OAuth token
  → 现有 sync PR
  → 现有 sync files / patches
  → 现有 create_review_job
  → Celery.delay(review_job_id)
  → 已有 worker / OpenRouter / findings / 前端轮询
```

- 同步和建 job 必须在 Celery（或同等队列）里做，不能在 webhook 请求里跑完
- 前端 60s 轮询 job 状态保留：Webhook 替代的是「要不要去 GitHub 拉 PR」，不是「浏览器怎么知道 AI 做完了」
- 9B 可以暂时「每次 synchronize 都建 job」；重复 job 的抑制放到 9C

状态：已完成（push 后 worker 自动 `GET .../files`、`create_review_job`、走现有 `execute_review_job`；webhook HTTP 马上 200，不等 OpenRouter。仓库需事先被该用户 Sync 进 CodeGuard）

#### Phase 9C: Reliability & Idempotency

目标：同一投递不处理两遍；连推不刷一串 review job。

1. 投递幂等：表 `github_webhook_events`，`UNIQUE(delivery_id)`。同一 `X-GitHub-Delivery` 重放则 ignore。
2. 业务幂等：该 PR 已有 `pending` / `processing` 的 review job 则 skip，不再 `create_review_job`。不同 delivery 的连续 `synchronize` 单靠 delivery 表挡不住。

状态：已完成（`github_webhook_events.delivery_id` 唯一约束防止同一 delivery 重放；PR 行锁 + active job 部分唯一索引防止 `pending` / `processing` job 重复创建；手动与 webhook 入口复用同一检查。）

#### Phase 9D: GitHub Comment（可选 / 最后做）

目标：把 findings 汇总评论写回 PR。第一轮不做。

若还订阅了 `issue_comment`，自己的评论可能再打进 webhook 形成环。即使做 9D，也继续只订 `pull_request`，并过滤 bot 自己的事件。

GitHub App / Installation token 不在本步范围，作为以后的 Version 2。

状态：可选，暂缓。

Step 9 总状态：已完成 Phase 9A–9C。9D 暂缓。

### Step 10: 部署与工程化完善

目的：把项目从本地开发原型提升为可部署、可维护的工程系统。

第一阶段约束：

- 正式业务部署以严格 0 成本为目标，不启用会自动产生按量账单的运行资源
- Northflank Developer Sandbox 承载后端运行时（2 Service + 2 Job）；Neon / Upstash / CloudAMQP 保存持久数据和队列，用户数据不落到临时容器磁盘
- Vercel Hobby 仅用于当前个人学习和作品集阶段；未来商业化时升级或迁移
- GCP Free Tier / credit 仅作为隔离的 Terraform、VM、Cloud Run、GKE 练习环境，不接入 CodeGuard 真实数据和生产密钥
- 免费平台没有生产 SLA；代码、镜像、迁移、密钥、CI/CD 和回滚仍按产品级流程建设

第一阶段目标架构：

```text
Browser
  → Vercel Next.js（仅 Production 域名用于登录 / Cookie）
  → 同源 /api rewrite
  → Northflank FastAPI Service
  → CloudAMQP（Little Lemur，AMQPS）
  → Northflank Celery Worker Service
  → OpenRouter
  → Neon PostgreSQL

GitHub webhook
  → Northflank FastAPI `/webhooks/github`（不经过 Vercel）

Northflank Cron Job
  → 每 6 小时运行 mark_abandoned_jobs_as_failed（按 job 的 updated_at，阈值 3 小时）

FastAPI
  → Upstash Redis（分布式限流）
```

#### Phase 10A: Production Baseline

- 加固后端 Dockerfile：非 root 用户、可复现构建、API / worker / migration / cron 复用同一镜像
- 拆分 liveness / readiness；liveness 不访问外部服务，readiness 检查必要依赖
- 增加不含密钥的 `.env.example` 和生产配置校验
- 所有业务持久数据继续写入 Neon；容器磁盘只保存临时文件和受限日志

状态：实现已完成（后端镜像改为非 root 且仅复制运行/迁移文件；增加 `/health/live` 与 `/health/ready`；Redis 故障降级但不触发容器重启；生产环境强制 HTTPS、安全 Cookie 和足够长度的 JWT/Webhook secret；Compose 增加健康检查和日志轮转）。自动化测试已通过；Docker 构建需在启用 Docker Desktop WSL integration 后补验。

#### Phase 10B: Upstash Redis Rate Limiting

- Redis 不为了堆技术而缓存数据库数据，第一项真实业务用途是分布式限流
- 对 OAuth、repository / PR / files sync、review job 创建按 IP / user / object 限流
- review 和 sync 写路径在 Redis 不可用时 fail closed；GET 读路径不依赖 Redis
- Webhook delivery 与 review job 幂等继续使用 PostgreSQL，不迁移到 Redis
- Upstash REST Redis 不作为 Celery broker，RabbitMQ 链路保持不变

状态：实现已完成。后端通过 Upstash REST 的单次原子 `EVAL` 执行固定窗口计数；OAuth 按哈希后的客户端 IP 限制为每 10 分钟 20 次，sync 共享每用户 10 分钟 30 次并增加每对象每分钟 6 次，review 限制为每用户每小时 5 次且每个 PR 每 10 分钟 2 次。超限返回 `429 + Retry-After`，Redis 不可用时受保护路径返回 `503`；普通 GET、health、logout、webhook 和 Celery 链路不依赖限流。所有配额均可通过环境变量调整，生产环境强制 `RATE_LIMIT_ENABLED=true`。

本地开发默认可以设置 `RATE_LIMIT_ENABLED=false` 以避免离线环境阻塞写操作。需要联调真实 Upstash 时改为 `true`，并确认 `UPSTASH_REDIS_REST_URL`、`UPSTASH_REDIS_REST_TOKEN` 可用。`RATE_LIMIT_TRUSTED_PROXY_HOPS` 默认是 `1`；Vercel rewrite 已接入，若限流 key 不准，再按实际 `X-Forwarded-For` 链调整，不要盲目加大 hops。

#### Phase 10C: Frontend / Cookie / OAuth

- Vercel 将 `/api/:path*` rewrite 到 Northflank API，浏览器始终使用同源 `/api`
- GitHub OAuth callback 使用 Vercel `/api/auth/github/callback`，再由 rewrite 转发到 FastAPI
- 保持第一方 `httpOnly + Secure + SameSite=Lax` Cookie，避免跨平台域名导致 session 丢失
- GitHub webhook 使用 Northflank API 的稳定公网 URL 直连，不经过 Vercel
- 登录只使用 Vercel Production 域名；Preview 部署每次换主机名，OAuth state Cookie 对不上，会 `Invalid OAuth state`

状态：已完成。前端 `next.config.ts` rewrite `/api/:path*` → `API_ORIGIN`；生产 Cookie 写在 Vercel 域名上。GitHub App 登记 Production callback。Preview URL 不用于登录。

#### Phase 10D: Northflank Runtime

- Service 1：FastAPI API（`nf-compute-10`，公开 HTTP 8000，`/health/live`）
- Service 2：Celery worker，同一镜像，CMD override，`concurrency=1 --without-gossip --without-mingle --without-heartbeat`，不公开端口
- Broker：CloudAMQP Little Lemur（`amqps://`）。Northflank Sandbox 的 RabbitMQ Addon compute plan 全部灰色，无法在 0 成本下启用，因此不占用 Sandbox 的 1 个 Addon 名额
- Cron Job：每 6 小时运行 `mark_abandoned_jobs_as_failed`，替代占用第三个 Service 的常驻 Celery Beat
- 运行时环境变量注入 Neon、Upstash、OpenRouter、GitHub 和 CloudAMQP；不启用付费扩容、额外 Service、持久卷或超出 Sandbox 的资源

状态：已完成。生产上手动 Run AI review 可走完 `pending → processing → completed`。Cron 已成功执行。GitHub webhook 已改为 Northflank `/webhooks/github`，Redeliver 返回 200。对已 sync 仓库 `git push` 后是否自动出现 review job，仍待补一次手工验证。

#### Phase 10E: CI/CD

- GitHub Actions CI：后端 pytest、Alembic head / migration 检查、前端 lint / typecheck / `npm test` / build、Docker build
- 合并到 `main` 且 CI 全绿后，将后端镜像推到 `ghcr.io/<owner>/repo-guard-backend:<git-sha>` 和 `:main`；PR 不推镜像
- API 与 worker 均为 Northflank Deployment（外部镜像），不再用 Combined 从 Git 构建；镜像路径 `ghcr.io/<owner>/repo-guard-backend:main`
- Sandbox 没有「先迁移再部署」的发布管道。关掉自动更新等于每次发版都手点，所以生产跟 `:main` 自动拉新镜像
- 改表结构：本地对生产 Neon 跑 `alembic upgrade head`，确认完成后再合入 `main`。没有结构变更则直接合入
- 删列 / 删表 / 改列名会让仍在跑的旧进程对着新库摔；日常只加表、加列。Northflank migrate Job 留作备用，不是日常路径
- 前端由 Vercel Git Integration 发布；PR 生成 Preview，`main` 发布 Production
- 不用 Terraform 管理 Northflank Service / Job / Addon

状态：已完成。

#### Phase 10F: Observability / Rollback / Zero-Cost Guardrails

状态：跳过。当前全是免费档，排障用 Northflank Logs、GitHub webhook 投递记录和 CloudAMQP 控制台即可。出问题或用量顶满再补，不单独做一阶段。

原计划（未做）：

- API / worker 结构化日志包含 delivery ID、review job ID 和 Celery task ID
- 监控 API 5xx、worker 离线、RabbitMQ 队列堆积、stale job、migration 失败
- API / worker 按 image digest 回滚；应用回滚不自动执行 Alembic downgrade
- GHCR 只保留必要镜像版本；限制日志体积和保留期
- 定期检查 Vercel、Northflank、Neon、Upstash、CloudAMQP/GHCR 的免费额度与政策变化

#### Phase 10G: Isolated GCP Learning Lab

- 使用 GCP credit / Always Free 单独练习 Terraform、VPC、IAM、Compute Engine、Cloud Run 和 GKE
- 不注入 CodeGuard 的 Neon、RabbitMQ、GitHub OAuth、Webhook 或 OpenRouter 生产密钥
- 每个实验设置预算告警和销毁步骤，结束后执行 `terraform destroy`
- Kubernetes / Terraform 学习成果后续再迁移到正式付费生产方案，不把单节点免费环境描述为高可用生产集群

状态：未作为产品路径执行。10A–10E 已完成，10F 跳过。

### Step 11: 产品化补强

目的：在 Step 8 功能闭环已经可用的前提下，把安全、体验、测试和模型质量补到更接近工业产品。每一条都标明在优化哪一步的哪一点。

状态：11A 大部分已落地。11A-3 取消，不再排期。打包、review 执行、webhook 和展示层关键路径已有自动化测试。安全加固、UI、模型质量未开始。

#### 11A: Review 输入打包

针对 Step 6 chunking 和 Step 7B worker 执行。旧 combined / hunk 两档已从运行时移除（git 历史可查）。现在：过滤噪声 → GitHub 窗口 → 贪婪 pack。

硬约束（高于「任务必须 complete」、高于「少打几次 API」）：

- 过滤名单之外、PR 里该审的文件一个都不能 skip。装不进当前 pack 的部分进入下一个 pack，禁止丢掉文件后半段。
- 产出必须有用：切分时要有变更前后的源码上下文。库里只有 GitHub `patch`（hunk 自带约 3 行），不够就用 Contents API / blob `sha` 拉该文件，再取 hunk 附近行。全文只在这次 review 进内存，不写库。
- 生产是 `openrouter/free`，窗口未知；pack 字符预算按 `REVIEW_PACK_MAX_CHARS × 0.9`（`PACK_CONTENT_BUDGET_RATIO`）预留 prompt/回复空间，不是按某个模型的 token 上限。
- 任务墙钟超时 1 小时（Celery soft limit）。到点重试一次；第二次再超时或失败则标 `failed`。不是靠 skip 文件来换 `completed`。

已落地：

1. **忽略噪声文件**（11A-1）  
   lockfile、`__pycache__`、图片、生成物等不送模型。
2. **取消 combined / chunk 两档，次数不封顶**（11A-2）  
   每个 pack 一次模型请求。没有 `REVIEW_PACK_MAX_CALLS`。装不下就开下一 pack，余量不丢。
3. **单文件超过一个 pack：拉 GitHub 文件，按 hunk 窗口切**（11A-2）  
   用已存的 `sha` / `contents_url` 取 PR head 正文（Contents 403/缺失则走 git blob）。每个变更窗口 = `@@` 行号 ± `REVIEW_CONTEXT_LINES`（默认 40），相邻窗口重叠则合并。  
   窗口仍大于预算 → 按行切开后继续装后续 pack。GitHub 没给 `patch` 的过大文件同样拉全文再切。
4. **模型失败与 1 小时超时**（11A-4）  
   某次 pack 调用失败记进 `error_message`，其余 pack 继续跑；全部失败才 `failed`。  
   Celery `soft_time_limit=3600`，`time_limit=4200`（给写库和 `self.retry()` 留时间）。第一次超时整单再跑，第二次写 `failed`。  
   单次 OpenRouter 超时不重试；空内容 / 5xx / 429 才对同一 payload 最多再打 3 次，每次重试前等 35s（两次合计 70s，覆盖 20 RPM 窗口）。  
   `OPENROUTER_READ_TIMEOUT` / `wait_for` 为 7200 秒，大于 soft limit，墙钟掐断只认 Celery。  
   过期 `processing` 回收每 6 小时跑一轮，按每个 job 自己的 `updated_at`；阈值 10800 秒（3 小时）。
5. **单测**（11A-5）  
   噪声过滤、每个业务文件都进某个 pack、大文件余量进后续 pack、窗口带上下文、无 patch 文件仍覆盖、超长单行切开、GitHub raw/403→blob/base64 JSON。大 PR、部分 pack 失败、全部失败已有自动化用例，见 [测试与本地命令](testing.md)。

清单：

- [x] **11A-1 忽略噪声文件**
- [x] **11A-2 全覆盖打包 + GitHub 上下文窗口**
- [x] **11A-3 单次请求超限再拆** — 取消
- [x] **11A-4 模型失败与 1 小时超时**
- [x] **11A-5 打包单测** — 无 skip / 窗口上下文 / 无 patch，以及大 PR、部分成功、全部失败。超限再拆不再测

合入 / 上生产前 checklist（环境变量在 Northflank api + worker，不是 Neon）：

- Worker CMD：`celery -A app.core.celery_app:celery_app worker -l INFO --concurrency=1 --without-gossip --without-mingle --without-heartbeat`（关掉 gossip / mingle / heartbeat 后才不会空转打满 CloudAMQP 月额度）
- `OPENROUTER_READ_TIMEOUT=7200`
- `CELERY_TASK_SOFT_TIME_LIMIT=3600`
- `CELERY_TASK_TIME_LIMIT=4200`
- `CELERY_TASK_RECLAIM_INTERVAL_SECONDS=21600`
- `REVIEW_JOB_STALE_PROCESSING_SECONDS=10800`
- `REVIEW_PACK_MAX_CHARS=8000`
- `REVIEW_CONTEXT_LINES=40`
- `REVIEW_RETRY_ATTEMPTS=3`（只作用于单次调用的空内容/5xx/429，不是整单 3 次；每次重试前固定等 35s）
- 去掉 `REVIEW_PACK_MAX_CALLS` 以及旧的 `REVIEW_MAX_COMBINED_*` / `REVIEW_MAX_PATCH_CHARS`
- Cron / Beat 间隔与 `CELERY_TASK_RECLAIM_INTERVAL_SECONDS` 一致（`0 */6 * * *`）
- 这次没有新的 Alembic，不必改 Neon

#### 安全与鉴权

- [x] **IDOR 自动化测试** — 针对 Step 8 读接口：非属主的 `GET /review-jobs/{id}`、review 列表，以及 PR / 文件读取为 404；查询把调用者 `user_id` 绑进 SQL。用 mock session，不是两个用户打真实库。
- [ ] **读路径复检 GitHub 权限** — 针对 Step 3 和 Step 8 的 GET：租户模型目前是「谁 sync 进库」，不是 GitHub ACL。协作者被移出仓库后，库里的 patch / findings 仍可读。
- [ ] **GitHub token 落库加密** — 针对 Step 3：`users` 表现在明文存 GitHub access token。
- [ ] **队列与 worker 隔离** — 针对 Step 7B/7C：Celery 按 `review_job_id` 执行和标失败，不校验 user。RabbitMQ 必须保持内网；暴露队列等于可触发任意 review。
- [ ] **Cookie session 加固清单** — 针对 Step 8A：核对 SameSite / CSRF、CSP；补按对象的速率限制和审计日志。
- [ ] **资源 ID 策略** — 针对 Step 8D 的 `?jobId=` / `/files/{id}` 以及 Step 3 的自增主键：跨用户已 404，同一账号仍可枚举自己的整数 id。多租户或分享链接前再评估。

#### UI / UX

- [ ] **信息层级与导航** — 针对 Step 8：PR 标题、分支、review 状态应一眼能扫，而不是先翻表。
- [ ] **Job 选中态** — 针对 Step 8C：当前靠点 `#id` 选中，不够明显。
- [ ] **Findings 与 diff 同屏** — 针对 Step 8D：现在要跳到另一页才能看行内评论；可做左右分栏或文件页内嵌列表。
- [ ] **空状态 / 加载 / 密度** — 针对 Step 8B/8C/8D：补骨架屏、空状态、失败重试、暗色与基本移动端。
- [ ] **路由级错误与鉴权边界** — 针对 Step 8A–8D：补共享 authenticated layout、`loading.tsx` / `error.tsx` / `not-found.tsx`。
- [ ] **Review 状态反馈** — 针对 Step 8C：创建 job 后自动选中该 job；文件 diff 页也应刷新活跃 job。
- [ ] **视觉风格** — 针对 Step 8：目前是 shadcn 默认件 + 表格。可用已安装的 lucide-react 补图标。

#### 可靠性、模型与测试

- [ ] **OpenRouter 空内容 / 非 JSON** — 针对 Step 5 和 Step 6：免费/路由模型会返回 `content: null` 或 `User Safety: safe`。可换具体 chat 模型、加强日志、按模型可选 `response_format`。
- [ ] **单次生成墙钟超时** — 针对 Step 7E：httpx `read` 只限制两次 socket 读的间隔；已用 `asyncio.wait_for` 兜底，需保证 rebuild worker 后生效。
- [ ] **前端轮询间隔** — 针对 Step 8C：当前 `refetchInterval = 60000`。可缩短，或后续改 SSE/WebSocket。
- [x] **Chunk / pack 路径测试** — 大 PR、部分成功、全部失败、去重与 `file_path` 已有。部分 pack 失败当前仍写成 `completed`。11A-3 不在测试范围内。用例见 [测试与本地命令](testing.md)。
- [x] **展示层关键路径** — 针对 Step 8C/8D：Vitest 覆盖触发 review、钉选 job、无效 `jobId`。按 severity 过滤 findings，以及浏览器 E2E，还没有。
- [x] **API / Webhook 测试** — 针对 Step 3、7、9：OAuth、HMAC / ping、delivery 重放、活跃 job 去重、同步与 review 路径已有 mock 测试。不是对真实 GitHub 的集成。
- [ ] **GitHub API 分页** — 针对 Step 3：仓库和 PR 列表已跟随 `Link`，并有测试。PR files 仍只取第一页；测试锁的是这个现状。
- [ ] **Webhook pipeline 重试与失败追踪** — 针对 Step 9B：为 sync PR/files 和创建 job 的后台任务增加瞬时错误重试、退避和最终失败状态。
- [ ] **Worker 并发执行保护** — 针对 Step 7B/7E：终态 job 已会跳过，但同一 `pending` / `processing` job 仍可能被多个 worker 并发消费。
- [ ] **Review 查询负载拆分** — 针对 Step 8C：列表返回摘要，选中后再请求 `GET /review-jobs/{id}`。
- [ ] **Worker 非 root 运行** — 针对 Step 7E 和 Step 10：当前 Celery worker 以 root 跑，有 SecurityWarning。
- [ ] **Redis `/health` 在受限网络下失败** — 针对 Step 2：校园网等环境 DNS 拦 `upstash.io` 时健康检查失败；review 主路径并不走 Redis。
- [ ] **配置与迁移工程化** — 针对 Step 2 / Step 10：`.env.example` 已有一份；仍需保证 Alembic autogenerate 导入全部 model，并在 CI 中校验迁移链与 ORM metadata 一致。

#### 产品边界

- [x] **模型选择** — PR 页可选白名单模型（`openrouter/free`、`nvidia/nemotron-3-ultra-550b-a55b:free`）。未知 id 返回 422。Webhook 仍用服务器默认模型。
- [ ] **组织 / 多成员** — 针对 Step 3：没有 org、没有分享仓库。
- [ ] **评论写回 GitHub** — 即 Step 9D。

### Step 12: Review Agent

目的：在现有 review job 上，让模型自己决定要读哪些 PR 信息，再写出与现在相同的 findings。

当前 `OpenRouterReviewProvider.review_content` 只发一轮 chat，并要求 JSON findings。请求里没有 `tools`。Python 在 `execute_review_job` 里已经滤文件、拉正文、打好窗口。

每日步骤、工具该包装哪些现有函数、以及哪一天才进 Celery，写在 [Agent 计划](agent-plan.md)。Day 1 不进 API、不进 Celery、不改表。队列继续 Celery。

状态：未开始

## 已完成能力

- 项目基础初始化
- FastAPI 后端基础结构
- PostgreSQL / Redis 健康检查
- SQLAlchemy + Alembic 数据迁移
- GitHub 登录与用户落库
- JWT 基础认证与 `/auth/me`
- Repository / Pull Request / files / patch 同步
- Review job 数据模型与 GitHub 上下文窗口打包
- OpenRouter 在线模型调用；过滤噪声后按 pack 请求；无 patch 的业务文件仍拉 GitHub 正文覆盖
- Review findings 数据表、结构化输出解析、落库与去重
- pack 失败记错误并继续其余 pack；全部失败才 `failed`
- `GET /review-jobs/{id}`、`GET /pull-requests/{id}/review-jobs`
- RabbitMQ + Celery；`POST /pull-requests/{id}/review-jobs` 返回 `202 Accepted`
- Celery task 级重试；满 1 小时整单再跑一次，第二次超时写回 `failed`
- worker 层错误写回 `review_jobs.error_message`
- 终态 job 幂等跳过
- Celery Beat / Northflank Cron 每 6 小时回收 stale `processing` jobs（按 job `updated_at`，阈值 3 小时）
- 本地 compose：api + worker + beat + rabbitmq
- task 层失败路径自动化测试
- 后端 CORS + GitHub OAuth 回跳前端 + httpOnly cookie session
- 前端登录 / 当前用户 / 登出、仓库与 PR 列表、PR 详情（Sync files、Run AI review、轮询）
- 前端按 job 展示 summary / findings，支持 severity 与 file 过滤
- 前端文件 diff（行号 + 按 finding 高亮）；无效 `jobId` 显示 not found
- Review job / PR file 读接口按 `Repository.user_id` 做对象级隔离，非属主 404 已有自动化测试（mock session）
- `POST /webhooks/github`：原始 body HMAC，无 JWT；仅 `opened` / `synchronize` 入队
- Celery webhook 任务复用 sync PR / files / `create_review_job` / `execute_review_job_task`
- `github_webhook_events` + `UNIQUE(delivery_id)`；同一 PR 只有一个 `pending` / `processing` job
- 9C 自动化测试：新 delivery、重复 delivery、broker 发布失败补偿、ping、active job 复用/新建
- 自动化测试：后端 125（`pytest -q`）、前端 30（`npm test`）。CI 两头都跑。清单在 [测试与本地命令](testing.md)
- 开发环境用 ngrok 暴露 `localhost:8000`（非架构组件）；生产 webhook 直连 Northflank API
- Vercel Hobby 托管前端；浏览器只请求同源 `/api`
- Northflank Sandbox：API + Celery worker（GHCR `:main`）+ reclaim Cron + 备用 migrate Job
- CloudAMQP Little Lemur 作为生产 RabbitMQ；本地 Compose 仍用容器内 RabbitMQ + Beat

当前已经具备手动与自动两条入口。9C 已阻止同一 delivery 重放和同一 PR 的活跃 job 重复创建。
