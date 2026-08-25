# CodeGuard AI

CodeGuard AI 是一个面向开发者的 AI Code Review SaaS 项目。它的目标不是简单调用大模型生成点评，而是完整实践一个真实工程项目从 GitHub 集成、数据同步、AI review 到后续异步任务和云部署的全流程。

## 项目目的

这个项目用于系统学习和展示现代软件工程能力，包括：

- Full Stack 开发
- AI 工程
- GitHub 平台集成
- 异步任务架构
- 数据建模与迁移
- 云原生与后续部署能力

最终目标是把它做成一个可持续迭代、可部署、可写进简历的真实 MVP。

## 技术栈

当前已采用或已规划的主要技术：

- Frontend: Next.js, React, TypeScript, Tailwind CSS, shadcn/ui, TanStack Query, axios, React Hook Form, Zod
- Backend: FastAPI, SQLAlchemy 2, Pydantic, Alembic, httpx
- Database: Neon PostgreSQL
- Cache: Upstash Redis
- GitHub Integration: GitHub App / OAuth, GitHub REST API
- AI Review: OpenRouter API（当前），后续可扩展为更多 provider
- Async / Infra: RabbitMQ, Celery Worker, Celery Beat（已接入）；后续 Kubernetes / Terraform
- Local Orchestration: Docker Compose（api + worker + beat + rabbitmq）
- CI/CD: Github Actions

Architecture 最终完成的流程：Github -> Webhook -> BackendAPI -> RabbitMQ -> Celery -> OpenRouter -> Postgres -> Frontend

### 前端技术落地

README 原定前端栈与当前使用情况：

- 已使用：Next.js, React, TypeScript, Tailwind CSS, shadcn/ui（Button / Table / Card）, TanStack Query, axios
- 已安装但未在业务代码中使用：React Hook Form, Zod, lucide-react
- 未使用原因：8C 触发 review 目前是单按钮，尚未做模型选择表单；lucide-react 预留给后续 UI polish（Step 11）

## 当前系统流程

目前已经打通的主流程如下：

1. 用户在前端通过 GitHub 登录（httpOnly cookie session）
2. 后端保存用户信息和访问凭证
3. 前端展示已同步 repositories，并支持手动 sync
4. 前端展示某个 repository 下的 pull requests，并支持手动 sync
5. 后端可同步某个 pull request 下的 changed files 和 patch
6. `POST /pull-requests/{id}/review-jobs` 创建 job（`pending`）并入队，返回 `202 Accepted`
7. Celery worker 后台执行 review（小 PR 单次请求，大 PR chunking）
8. 调用 OpenRouter 生成结构化 `summary` + `findings` 并落库
9. 前端 PR 详情触发 review，并以 TanStack Query 轮询 `pending -> processing -> completed / failed`
10. 前端展示 `result_summary` 与 findings，可按文件 / 严重级别过滤，并跳到对应 diff 行号
11. Celery Beat 定期回收卡在 `processing` 的僵尸 job

## 项目路线图

整个项目可以分为 11 个主要步骤。每一步都对应一个明确的工程目标，而不是为了堆技术而堆技术。Step 1–8 已完成功能闭环；Step 9–10 是自动化与部署；Step 11 是对已完成步骤的产品化补强，不阻塞 Step 9。

### Step 1: 项目初始化

目的：建立可持续迭代的项目骨架。  
要做的事情：

- 初始化 monorepo
- 建立 `frontend/` 和 `backend/` 基础目录
- 补充根目录 `README`、后续文档和基础规范

状态：已完成

### Step 2: Backend 基础设施

目的：先打通后端基础依赖，让服务具备最小可运行能力。  
要做的事情：

- 搭建 FastAPI 应用
- 连接 Neon PostgreSQL
- 连接 Upstash Redis
- 建立 `/health` 健康检查
- 建立 SQLAlchemy + Alembic 基础迁移能力

状态：已完成

### Step 3: GitHub 身份与数据同步

目的：把 GitHub 用户、仓库、PR 数据同步进本地系统。  
要做的事情：

- GitHub 登录
- 用户落库
- JWT 认证与 `/auth/me`
- 同步 repositories
- 同步 pull requests
- 同步 pull request files / patch

状态：已完成

### Step 4: AI Review 输入准备

目的：把 PR diff 转换为模型可消费的输入。  
要做的事情：

- 建立 `review_jobs` 数据模型
- 建立 diff chunking 逻辑
- 支持小 PR 单请求 review
- 支持大 PR fallback chunking

状态：已完成

### Step 5: AI Review v1

目的：先把一版可运行的 AI review 链路跑通。  
要做的事情：

- 抽象 review provider 接口
- 接入 OpenRouter 在线模型
- 基于 `review_jobs` 执行同步 review
- 将 review summary 回写数据库

状态：已完成基础版本

### Step 6: 结构化 Review Findings

目的：把大段文本 review 结果升级为可展示、可定位、可扩展的数据结构。  
要做的事情：

- 增加 findings 数据表
- 保存 severity、summary、file_path、line range、suggestion
- 让模型输出结构化结果，而不只是纯文本 summary

状态：已完成基础版本

### Step 7: 异步任务系统

目的：把 AI review 从同步接口调用升级为真正后台执行。  
要做的事情：

- 引入 RabbitMQ
- 引入 Celery Worker
- 将 review job 提交到队列
- 支持任务状态轮询、失败重试和错误记录

建议按以下 5 个阶段推进：

#### Phase 7A: RabbitMQ + Celery 最小消息流

目标：先打通消息队列和 worker，不急着修改现有 review API。  
要做的事情：

- 启动 RabbitMQ
- 创建 Celery app
- 编写一个最小任务（如 `hello` / `add`）
- 启动 worker 并验证 `delay()` 后任务能够被消费

状态：已完成

#### Phase 7B: Celery 接入 review job 执行逻辑

目标：让 Celery worker 真正调用 `execute_review_job()`。  
要做的事情：

- 定义 review job task
- task 接收 `review_job_id`
- worker 在后台执行 review
- 结果继续写回 `review_jobs` / `review_findings`

状态：已完成

#### Phase 7C: API 改造为异步任务接口

目标：把创建 review job 的接口改成真正的异步接口。  
要做的事情：

- `POST /pull-requests/{id}/review-jobs` 只负责创建 job
- job 初始状态写为 `pending`
- API 将任务发送到 RabbitMQ
- 立即返回 `202 Accepted`

状态：已完成

#### Phase 7D: 状态轮询与查询规范

目标：让客户端可以通过 job 查询接口获取最新状态。  
要做的事情：

- 明确状态流转：`pending -> processing -> completed / failed`
- 基于 `GET /review-jobs/{id}` 查询状态
- 为前端轮询和后续展示层打基础

状态：已完成

#### Phase 7E: 可靠性与工程化补全

目标：把异步系统从“能跑”升级到“更接近真实工程”。  
要做的事情：

- 增加任务级重试（瞬时 HTTP/网络错误 + 指数退避）
- 增加超时控制（soft/hard time limit）
- 增加日志和错误记录（worker 写回 `review_jobs.error_message`）
- 终态 job 幂等跳过，避免 at-least-once 重复执行
- Celery Beat 自动回收 stale `processing` jobs
- 本地 `compose.yaml`：api + worker + beat + rabbitmq
- task 层失败路径自动化测试（soft timeout / 重试耗尽 / reclaim）

状态：已完成

Step 7 总状态：已完成 Phase 7A - 7E

### Step 8: Review 展示层

目的：让 review 结果真正可被用户消费。  
要做的事情：

- 前端 GitHub 登录与 session
- 展示 repositories / PRs / files
- 触发 review job，并轮询 `pending / processing / completed / failed`
- 展示 review findings
- 按文件和严重级别过滤
- 提供类似 GitHub review 的阅读体验

建议按以下 4 个阶段推进：

#### Phase 8A: 前端基础与登录

目标：先让浏览器能安全地调用后端。  
要做的事情：

- 后端补 CORS，允许 `frontend_url`
- 打通 GitHub OAuth 回跳到前端并保存 access token
- 建立 API client（axios + TanStack Query）
- 登录页 / 当前用户信息

状态：已完成

#### Phase 8B: Repo / PR 浏览

目标：用户能看到自己的仓库和 PR，而不必每次只靠 curl sync。  
要做的事情：

- 后端补 `GET` 列表接口（当前只有 sync `POST`）
- 前端仓库列表、PR 列表
- 手动 sync 按钮（复用现有 sync API）

状态：已完成

#### Phase 8C: 异步 Review 触发与状态

目标：在 UI 里走完 `202 + 轮询` 这条已存在的后端契约。  
要做的事情：

- 在 PR 详情触发 review job
- 轮询 job 状态
- 展示 `pending / processing / completed / failed` 和 `error_message`

状态：已完成

#### Phase 8D: Findings 阅读体验

目标：让结构化结果真正可消费。  
要做的事情：

- 展示 `result_summary` 与 findings 列表
- 按 `file_path`、`severity` 过滤
- 定位到文件和行号（接近 GitHub review 的阅读方式）

状态：已完成（MVP：点 job 查看 findings，点 finding 进入文件 diff 并滚到行号。左右分栏、行内发评论等产品深度见 Step 11）

Step 8 总状态：已完成 Phase 8A - 8D。展示层功能闭环已通，视觉与安全工程化补强见 Step 11。

### Step 9: GitHub Event-Driven Automation

目的：把 CodeGuard 从「用户主动点 Sync / Run AI review」升级为由 GitHub Pull Request 事件驱动的异步 review 系统。  
原则：**不重构已经工作的 AI pipeline**（Step 3–7 的 sync / `create_review_job` / Celery / OpenRouter）。Webhook 只接到这条链前面。

身份约束（第一轮不做 GitHub App）：

- 现有模型是 GitHub OAuth 用户 token，仓库挂在 `repositories.user_id` 上
- Webhook **没有** JWT / `current_user`
- 用 `payload.repository.id` → `repositories.github_repo_id` → owner 的 OAuth token
- 本地还没有该仓库则记日志并跳过，不在 webhook 里给陌生人建用户

开发环境公网入口（ngrok / Cloudflare Tunnel）只是把 `localhost` 暴露给 GitHub 的工具，**不是**正式架构组件，不要写进业务代码。生产入口属于 Step 10。

状态：未开始。下一步从 9A 动手。

#### Phase 9A: GitHub Webhook（验签 + 过滤，不跑 AI）

目标：GitHub 能把事件送到 CodeGuard，并证明请求真的来自 GitHub。

要做的事情：

- 增加 `POST /webhooks/github`（**不要** `Depends(get_current_user)`）
- 配置 `GITHUB_WEBHOOK_SECRET`；开发时用隧道提供公网 URL
- 用**原始 request body** 校验 `X-Hub-Signature-256`（HMAC SHA-256）；失败返回 401/403
- 只关心 `X-GitHub-Event: pull_request`，第一阶段只**入队处理** `opened` 和 `synchronize`
- 记录 `X-GitHub-Delivery`、event type、action；马上返回 2xx
- `ping` 以及未支持的 action：仍返回 2xx + 打日志，**不**当 4xx（否则 GitHub 设置页显示投递失败）

Webhook **不执行 AI、不等待 Celery、不调用 OpenRouter**。它只做：Verify → Validate →（9B 起才 Dispatch）→ Return。

建议实现顺序：

1. 确认现有 `users` / `repositories` / `pull_requests` 和 GitHub sync service
2. 定 endpoint 职责和文件位置
3. 配 secret 与隧道
4. 实现原始 body + HMAC
5. 过滤 `pull_request` + `opened` / `synchronize`
6. 用 GitHub 测试 webhook（含 ping）

状态：未开始

#### Phase 9B: 自动 Review Pipeline

目标：复用 Step 3–7，把 webhook 接到现有 sync 和 review job。不要再写第二套 webhook-only review service。

流程：

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

说明：

- 同步和建 job 必须在 Celery（或同等队列）里做，不能在 webhook 请求里跑完
- 前端 60s 轮询 job 状态**保留**：Webhook 替代的是「要不要去 GitHub 拉 PR」，不是「浏览器怎么知道 AI 做完了」
- 9B 可以暂时「每次 synchronize 都建 job」；重复 job 的抑制放到 9C

状态：未开始

#### Phase 9C: Reliability & Idempotency

目标：同一投递不处理两遍；连推不刷一串 review job。

两层幂等：

1. **投递幂等**：表 `github_webhook_events`，`UNIQUE(delivery_id)`。同一 `X-GitHub-Delivery` 重放则 ignore。
2. **业务幂等**：该 PR 已有 `pending` / `processing` 的 review job 则 skip，不再 `create_review_job`。  
   （不同 delivery 的连续 `synchronize` 单靠 delivery 表挡不住。）

状态：未开始

#### Phase 9D: GitHub Comment（可选 / 最后做）

目标：把 findings 汇总评论写回 PR。第一轮不做。

注意：若还订阅了 `issue_comment`，自己的评论可能再打进 webhook 形成环。即使做 9D，也继续只订 `pull_request`，并过滤 bot 自己的事件。

GitHub App / Installation token 不在本步范围，作为以后的 Version 2。

状态：可选，未开始

Step 9 总状态：未开始，下一阶段是 Phase 9A

### Step 10: 部署与工程化完善

目的：把项目从本地开发原型提升为可部署、可维护的工程系统。  
要做的事情：

- Docker 化
- 引入 RabbitMQ / Worker 部署方案
- Kubernetes / Terraform
- 监控、日志、告警
- CI/CD 与部署流水线

状态：未开始

### Step 11: 产品化补强（不阻塞 Step 9）

目的：在 Step 8 功能闭环已经可用的前提下，把安全、体验、测试和模型质量补到更接近工业产品。每一条都标明在优化哪一步的哪一点。  
状态：未开始

#### 安全与鉴权

- [ ] **IDOR 自动化测试** — 针对 Step 8 读接口的对象级隔离：用户 B 读取用户 A 的 `GET /review-jobs/{id}`、`GET /pull-requests/{id}/files/{fileId}` 必须 404。当前 join `Repository.user_id` 已经写了，但没有测试锁住。
- [ ] **读路径复检 GitHub 权限** — 针对 Step 3「同步仓库 / PR / files」和 Step 8 的 GET：租户模型目前是「谁 sync 进库」，不是 GitHub ACL。协作者被移出仓库后，库里的 patch / findings 仍可读。
- [ ] **GitHub token 落库加密** — 针对 Step 3「用户落库 / 访问凭证」：`users` 表现在明文存 GitHub access token。
- [ ] **队列与 worker 隔离** — 针对 Step 7B/7C：Celery 按 `review_job_id` 执行和标失败，不校验 user。RabbitMQ 必须保持内网；暴露队列等于可触发任意 review。
- [ ] **Cookie session 加固清单** — 针对 Step 8A「httpOnly cookie session」：核对 SameSite / CSRF、CSP；补按对象的速率限制和审计日志。
- [ ] **资源 ID 策略** — 针对 Step 8D 的 `?jobId=` / `/files/{id}` 以及 Step 3 的自增主键：跨用户已 404，同一账号仍可枚举自己的整数 id。多租户或分享链接前再评估。

#### UI / UX

- [ ] **信息层级与导航** — 针对 Step 8 整体展示层：PR 标题、分支、review 状态应一眼能扫，而不是先翻表。
- [ ] **Job 选中态** — 针对 Step 8C「在 PR 详情展示 job 状态」：当前靠点 `#id` 选中，不够明显。
- [ ] **Findings 与 diff 同屏** — 针对 Step 8D「接近 GitHub review 的阅读方式」：现在要跳到另一页才能看行内评论；可做左右分栏或文件页内嵌列表。
- [ ] **空状态 / 加载 / 密度** — 针对 Step 8B/8C/8D 的列表页：补骨架屏、空状态、失败重试、暗色与基本移动端。
- [ ] **视觉风格** — 针对 Step 8 展示层：目前是 shadcn 默认件 + 表格，没有品牌和设计 token。可用已安装的 lucide-react 补图标。

#### 可靠性、模型与测试

- [ ] **OpenRouter 空内容 / 非 JSON** — 针对 Step 5「接入 OpenRouter」和 Step 6「结构化输出解析」：免费/路由模型会返回 `content: null` 或 `User Safety: safe`，靠重试才成功。可换具体 chat 模型、加强日志、按模型可选 `response_format`。
- [ ] **单次生成墙钟超时** — 针对 Step 7E「超时控制」：httpx `read` 只限制两次 socket 读的间隔；已用 `asyncio.wait_for` 兜底，需保证 **rebuild worker** 后生效。
- [ ] **前端轮询间隔** — 针对 Step 8C「轮询 job 状态」：当前 `refetchInterval = 60000`，pending/processing 体感偏慢。可缩短，或后续改 SSE/WebSocket。
- [ ] **Chunk 路径集成测试** — 针对 Step 6 findings 落库/去重 和 Step 7B worker 执行：大 PR、部分成功、全部失败、路径 fallback 仍主要靠手工。不阻塞 Step 9，但应补进自动化。
- [ ] **展示层自动化** — 针对 Step 8C/8D：触发 review、选中 job、过滤 findings、无效 `jobId` 显示 not found，目前只有手工步骤。
- [ ] **Worker 非 root 运行** — 针对 Step 7E 本地 compose 和 Step 10「Worker 部署方案」：当前 Celery worker 以 root 跑，有 SecurityWarning。
- [ ] **Redis `/health` 在受限网络下失败** — 针对 Step 2「`/health` 健康检查」：校园网等环境 DNS 拦 `upstash.io` 时健康检查失败；review 主路径并不走 Redis。

#### 产品边界（与 Step 9 的交界，但不替代 webhook）

- [ ] **模型选择表单** — 针对 Step 8C 触发 review：单按钮写死 `openrouter/free`。若要可选模型，再用已安装的 React Hook Form + Zod。
- [ ] **组织 / 多成员** — 针对 Step 3 的「一用户镜像自己的 GitHub」模型：没有 org、没有分享仓库。
- [ ] **评论写回 GitHub** — 即 Step 9D，不在 Step 8 范围；完成 9A–9C 后再做。

## 当前进度

目前已经完成：

- 项目基础初始化
- FastAPI 后端基础结构
- PostgreSQL / Redis 健康检查
- SQLAlchemy + Alembic 数据迁移
- GitHub 登录与用户落库
- JWT 基础认证与 `/auth/me`
- Repository 同步
- Pull Request 同步
- Pull Request files / patch 同步
- Review job 数据模型
- Diff chunking
- OpenRouter 在线模型调用
- 小 PR 单请求 review，大 PR fallback chunking
- Review findings 数据表
- 结构化 review 输出解析
- findings 落库与去重
- chunk 模式失败重试与部分成功保留
- `GET /review-jobs/{id}` 查询接口
- RabbitMQ + Celery 最小消息流
- Celery worker 后台执行 `execute_review_job()`
- `POST /pull-requests/{id}/review-jobs` 异步化为 `202 Accepted`
- `GET /pull-requests/{id}/review-jobs` 历史任务列表接口
- Celery task 级重试（瞬时错误 + 指数退避）
- Celery soft/hard time limit，超时写回 `failed`
- worker 层错误写回 `review_jobs.error_message`
- 终态 job 幂等跳过
- Celery Beat 自动回收 stale `processing` jobs
- 本地 compose：api + worker + beat + rabbitmq
- task 层失败路径自动化测试
- 后端 CORS + GitHub OAuth 回跳前端 + httpOnly cookie session
- 前端登录 / 当前用户 / 登出
- `GET /repositories`、`GET /repositories/{id}/pull-requests`、`GET /pull-requests/{id}`、`GET /pull-requests/{id}/files`、`GET /pull-requests/{id}/files/{fileId}`
- 前端仓库列表与手动 sync
- 前端 PR 列表与手动 sync
- 前端 PR 详情：Sync files、Run AI review、轮询 job 状态与 `error_message`
- 前端按 job 展示 `result_summary` / findings，支持 severity 与 file 过滤
- 前端文件 diff（行号 + 按 finding 高亮），无效 `jobId` 显示 not found 而不改用其他 job
- Review job / PR file 读接口按 `Repository.user_id` 做对象级隔离（缺 IDOR 自动化测试，见 Step 11）

当前已经具备可在浏览器里登录、同步仓库与 PR、触发 AI review、轮询状态并阅读 findings 的完整展示层。对象级 user 隔离已有，但尚未用自动化测试锁住；UI 仍是功能向 MVP。

从路线图角度看，当前已经完成 Step 1 到 Step 8D。下一步是 Step 9（Webhook 自动化）。安全、UI、模型质量与测试债放在 Step 11，不阻塞 Step 9。

## 当前核心数据模型

已建立的主要数据表：

- `users`
- `repositories`
- `pull_requests`
- `pull_request_files`
- `review_jobs`
- `review_findings`

这些表已经可以支持 GitHub 数据同步、结构化 AI review 和 findings 存储流程。

## 下一步计划

展示层 MVP 已完成。按优先级推进：

1. Step 9：从 9A 开始（公网可达 + HMAC 验签 + 事件过滤，不跑 AI）；9B 接现有 sync/Celery；9C 两层幂等；9D 评论可选
2. Step 10：部署、监控、CI/CD、非 root worker 等工程化
3. Step 11：安全测试、UI polish、模型质量与集成测试（可与 9/10 并行，但不作为 9 的前置）

chunk 模式的更系统化集成测试已记入 Step 11，不阻塞 webhook。

## 项目状态

当前项目已完成 GitHub 集成、结构化 AI review、异步任务系统，以及前端登录、Repo/PR 浏览、触发 review 与 findings 阅读。用户可以在浏览器里走完「登录 → sync → Run AI review → 点 job 看 findings → 点进文件看行内评论」。下一步是 Step 9A：`POST /webhooks/github` + HMAC 验签 + 只记录 `opened`/`synchronize`，不在 webhook 里跑 AI。

## 当前阶段测试计划

Step 7E 的 task 层失败路径已经用自动化测试锁住。Step 8 展示层目前以手工验证为主。结构化 review 在不同输入规模下的稳定性测试，以及 IDOR 测试，已记入 Step 11。

已完成验证：

- 小 PR 可走单次 review 请求
- `summary` 与 `findings` 可成功解析
- `summary` 与 `findings` 可成功写入数据库
- `review_jobs` 接口能够返回结构化结果
- compose 可启动 api / worker / beat / rabbitmq
- task 层 soft timeout 会写回 `failed`
- task 层瞬时错误重试耗尽会写回 `failed`
- Beat reclaim task 会调用回收逻辑
- 前端 GitHub 登录 / 登出 / session 保持
- 前端仓库列表与 PR 列表，刷新走 GET 而不自动 sync GitHub
- 前端 PR 详情可触发 review 并轮询 `pending / processing / completed / failed`
- 点 review job 可展示该 job 的 summary 与 findings，过滤后列表会变
- 点 finding 可进入对应文件 diff 并定位行号；无效 `jobId` 显示 not found

仍建议补完的测试（Step 11，不阻塞 Step 9）：

1. 小 PR 成功路径测试
   - 条件：改动总量小于 1000 行，且文件数不超过 30
   - 预期：`total_chunks = 1`
   - 预期：`status = completed`
   - 预期：`result_summary` 不为空
   - 预期：`findings` 可正常入库并随接口返回

2. 大 PR chunk 模式成功路径测试
   - 条件：改动总量超过单次 review 阈值
   - 预期：进入 chunk 模式，`total_chunks > 1`
   - 预期：成功 chunk 的 `summary` 会拼接进 `result_summary`
   - 预期：成功 chunk 的 `findings` 会写入数据库

3. chunk 失败重试测试
   - 条件：人为制造某个 chunk 返回非法 JSON 或解析失败
   - 预期：单个 chunk 会自动重试 3 次
   - 预期：3 次失败后记录失败日志
   - 预期：不会中断后续 chunk 的执行

4. 部分成功测试
   - 条件：部分 chunk 成功，部分 chunk 失败
   - 预期：整个 review job 仍可 `completed`
   - 预期：`error_message` 中包含失败 chunk 信息
   - 预期：数据库中保留成功 chunk 产出的 findings

5. 全部 chunk 失败测试
   - 条件：所有 chunk 都返回非法结果
   - 预期：整个 review job 标记为 `failed`
   - 预期：`error_message` 中包含失败原因汇总

6. 去重与路径补全测试
   - 条件：不同 chunk 产出重复 findings，或 finding 缺少 `file_path`
   - 预期：重复 findings 会被去重
   - 预期：chunk 模式下缺失的 `file_path` 会被 fallback 补齐

这些测试对应 Step 11「Chunk 路径集成测试」，不阻塞 Step 9。展示层已可消费已稳定的小 PR 成功路径。




Test command

联调整套后端（推荐）：
```
cd backend
docker compose up -d --build
```

开发迭代 API 时，可只起队列相关进程，本机热重载：
```
docker compose up -d rabbitmq worker beat
source venv/bin/activate
uvicorn app.main:app --reload
```

跑 7E task 层测试：
```
cd backend
source venv/bin/activate
pytest -q
```

source into environment: 
```
source venv/bin/activate
```

start backend (without compose api): 
```
uvicorn app.main:app --reload
```

start rabbitmq: 
```
docker compose up -d rabbitmq
```

start celery worker: 
```
celery -A app.core.celery_app:celery_app worker -l INFO
```

start celery beat: 
```
celery -A app.core.celery_app:celery_app beat -l INFO --schedule=/tmp/celerybeat-schedule
```

verify current user: 
```
curl http://127.0.0.1:8000/auth/me \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

sync REPO:
```
curl -X POST http://127.0.0.1:8000/repositories/sync \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

sync PR for [REPO_ID]:
```
curl -X POST http://127.0.0.1:8000/repositories/REPO_ID/pr/sync \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

sync PR files for [PR_ID]:
```
curl -X POST http://127.0.0.1:8000/pull-requests/PR_ID/files/sync \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

create review job:
```
curl -X POST http://127.0.0.1:8000/pull-requests/PR_ID/review-jobs \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "openrouter",
    "model_name": "openrouter/free"
  }'
```

verify all review jobs for [PR_ID]:
```
curl "http://127.0.0.1:8000/pull-requests/3/review-jobs" \
  -H "Authorization: Bearer <token>"
```

polling status of single review job:
```
curl "http://127.0.0.1:8000/review-jobs/<job_id>" \
  -H "Authorization: Bearer <token>"
```