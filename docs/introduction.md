# 项目简介

[返回 README](../README.md)

CodeGuard AI 的目标不是只调用一次大模型生成点评，而是走完一条真实链路：GitHub 集成、数据同步、AI review、异步任务和云部署。

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

- Frontend: Next.js, React, TypeScript, Tailwind CSS, shadcn/ui, TanStack Query, axios, React Hook Form, Zod
- Backend: FastAPI, SQLAlchemy 2, Pydantic, Alembic, httpx
- Database: Neon PostgreSQL
- Cache: Upstash Redis
- GitHub Integration: GitHub App / OAuth, GitHub REST API
- AI Review: OpenRouter API（当前），后续可扩展为更多 provider
- Async / Infra: RabbitMQ（本地 Compose + 生产 CloudAMQP Little Lemur）, Celery Worker；本地 Celery Beat，生产用 Northflank Cron 替代 Beat
- Local Orchestration: Docker Compose（api + worker + beat + rabbitmq）
- Hosting: Vercel Hobby（前端）、Northflank Developer Sandbox（API + worker + cron）
- CI/CD: GitHub Actions（PR 门禁；合入 `main` 后推 GHCR）。Northflank API / worker 从 `ghcr.io/<owner>/repo-guard-backend:main` 部署；前端走 Vercel Git Integration

完成形态：GitHub / 浏览器 → FastAPI → RabbitMQ → Celery → OpenRouter → Postgres → 前端轮询。

### 前端实际使用

- 已使用：Next.js, React, TypeScript, Tailwind CSS, shadcn/ui（Button / Table / Card）, TanStack Query, axios。PR 页用原生 `<select>` 选择白名单模型。
- 已安装但未在业务代码中使用：React Hook Form, Zod, lucide-react
- 未使用原因：模型选择还不是多字段表单；lucide-react 预留给后续 UI polish（Step 11）

## 系统运行流程

两条入口汇合到同一条 worker pipeline：浏览器手动「Run AI review」，或 GitHub webhook 自动触发。拓扑图在 [README](../README.md)。

1. 用户在前端通过 GitHub 登录（httpOnly cookie session），后端保存用户和 token
2. 前端 sync repositories / pull requests / changed files（patch 落库；全文不落库）
3. 手动 `POST /pull-requests/{id}/review-jobs` 创建 job（`pending`，`total_chunks=0`）并入队，返回 `202`
4. 或 GitHub `pull_request` `opened` / `synchronize` webhook 验签后入队，worker 先 sync files 再创建 job
5. Worker 过滤噪声 → 按 `sha` / `contents_url` 拉 PR head 正文 → hunk ±40 行窗口打包 → 每个 pack 打一次 OpenRouter
6. `summary` + `findings` 写入 Postgres；前端轮询 `pending → processing → completed / failed`
7. 满 1 小时整单再跑一次；第二次超时或全部 pack 失败则 `failed`
8. 本地 Beat / 生产 Cron 每 6 小时按 job 的 `updated_at` 回收卡死的 `processing`

重试分三层，不要混在一起：

| 层 | 行为 |
|---|---|
| 单次 OpenRouter 调用 | 空内容 / 5xx / 429 最多再打 3 次**同一段 payload**，每次重试前等 35s（两次合计 70s，避开 20 RPM）。超时不上这一层重试 |
| 单个 pack | 失败记进 `error_message`，继续后面的 pack；全部失败才 `failed`。11A-3 超限再拆已取消 |
| 整段 job | Celery soft limit 1 小时后 `self.retry()` **一次**；第二次 `failed` |

Worker 仍是 Celery prefork。同时在跑的 job 数等于子进程数；等 HTTP 时不会再领下一个 job。Agent 与 streaming 的队列决定见 [进度报告](progress.md#worker-并发)。

## 当前核心数据模型

- `users`
- `repositories`
- `pull_requests`
- `pull_request_files`
- `review_jobs`
- `review_findings`
- `github_webhook_events`

这些表支持 GitHub 数据同步、结构化 AI review 和 findings 存储。全文只在单次 review 的进程内存里，不写库。
