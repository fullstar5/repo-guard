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

- Frontend: Next.js, React, TypeScript, Tailwind CSS, shadcn/ui， TanStack Query, React Hook Form, Zod
- Backend: FastAPI, SQLAlchemy 2, Pydantic, Alembic, httpx
- Database: Neon PostgreSQL
- Cache: Upstash Redis
- GitHub Integration: GitHub App / OAuth, GitHub REST API
- AI Review: OpenRouter API（当前），后续可扩展为更多 provider
- Async / Infra（后续）: RabbitMQ, Celery, Docker, Kubernetes, Terraform
- CI/CD: Github Actions

Architeture最终完成的流程：Github -> Webhook -> BackendAPI -> RabbitMQ -> Celery -> OpenRouter -> Postgres -> Frontend

## 当前系统流程

目前后端已经打通的主流程如下：

1. 用户通过 GitHub 登录
2. 后端保存用户信息和访问凭证
3. 同步用户可访问的 repositories
4. 同步某个 repository 下的 pull requests
5. 同步某个 pull request 下的 changed files 和 patch
6. 基于 PR patch 创建 AI review job
7. 调用 OpenRouter 在线模型生成结构化 review 结果
8. 保存 review summary 与 findings，并支持按 review job 查询结果

## 项目路线图

整个项目可以分为 10 个主要步骤。每一步都对应一个明确的工程目标，而不是为了堆技术而堆技术。

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

状态：下一步立即开始

#### Phase 7B: Celery 接入 review job 执行逻辑

目标：让 Celery worker 真正调用 `execute_review_job()`。  
要做的事情：

- 定义 review job task
- task 接收 `review_job_id`
- worker 在后台执行 review
- 结果继续写回 `review_jobs` / `review_findings`

状态：未开始

#### Phase 7C: API 改造为异步任务接口

目标：把创建 review job 的接口改成真正的异步接口。  
要做的事情：

- `POST /pull-requests/{id}/review-jobs` 只负责创建 job
- job 初始状态写为 `pending`
- API 将任务发送到 RabbitMQ
- 立即返回 `202 Accepted`

状态：未开始

#### Phase 7D: 状态轮询与查询规范

目标：让客户端可以通过 job 查询接口获取最新状态。  
要做的事情：

- 明确状态流转：`pending -> processing -> completed / failed`
- 基于 `GET /review-jobs/{id}` 查询状态
- 为前端轮询和后续展示层打基础

状态：未开始

#### Phase 7E: 可靠性与工程化补全

目标：把异步系统从“能跑”升级到“更接近真实工程”。  
要做的事情：

- 增加任务级重试
- 增加超时控制
- 增加日志和错误记录
- 补充本地 `docker-compose.yml`

状态：未开始

Step 7 总状态：已完成方案设计，准备进入 Phase 7A

### Step 8: Review 展示层

目的：让 review 结果真正可被用户消费。  
要做的事情：

- 前端展示 repositories / PRs / files
- 展示 review findings
- 按文件和严重级别过滤
- 提供类似 GitHub review 的阅读体验

状态：未开始

### Step 9: 自动化触发

目的：让系统不再依赖手工点击同步和分析。  
要做的事情：

- 接入 GitHub webhook
- PR opened / synchronized 时自动同步
- 自动创建 review job
- 后续可支持自动评论回 GitHub

状态：未开始

### Step 10: 部署与工程化完善

目的：把项目从本地开发原型提升为可部署、可维护的工程系统。  
要做的事情：

- Docker 化
- 引入 RabbitMQ / Worker 部署方案
- Kubernetes / Terraform
- 监控、日志、告警
- CI/CD 与部署流水线

状态：未开始

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

当前已经具备一个最小可运行的结构化 AI review 输入、执行与查询链路。

从路线图角度看，当前已经完成 Step 1 到 Step 6 的基础版本，下一步进入 Step 7。

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

下一阶段建议优先完成：

1. 完成 Step 7A：RabbitMQ + Celery 最小消息流
2. 完成 Step 7B：让 worker 后台执行 `execute_review_job()`
3. 完成 Step 7C：把 review job 创建接口改成 `202 Accepted`
4. 完成 Step 7D：基于 `GET /review-jobs/{id}` 建立轮询语义
5. 完成 Step 7E：补任务级重试、超时、日志和 Compose

## 项目状态

当前项目已完成 GitHub 集成与结构化 AI review 的主干骨架，已经具备进入异步任务系统的前置条件。当前正准备开始 Step 7A：先打通 RabbitMQ 与 Celery 的最小消息流，再逐步接入 review job 执行链路。

## 当前阶段测试计划

当前阶段的目标不是继续扩功能，而是先验证结构化 review 链路在不同输入规模下是否稳定。

已完成验证：

- 小 PR 可走单次 review 请求
- `summary` 与 `findings` 可成功解析
- `summary` 与 `findings` 可成功写入数据库
- `review_jobs` 接口能够返回结构化结果

接下来计划补完的测试：

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

完成以上测试后，就可以进入下一步：正式开始 Step 7A，先验证 RabbitMQ + Celery 的最小任务链路，再逐步把 review job 接入后台执行。