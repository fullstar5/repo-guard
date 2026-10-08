# CodeGuard AI

CodeGuard AI 是面向开发者的 AI Code Review SaaS。浏览器里的「Run AI review」和 GitHub webhook 进同一条队列：FastAPI 把任务写入 RabbitMQ，Celery worker 打包 PR 窗口并请求 OpenRouter，结果写入 Postgres，前端轮询后展示 findings。

## 文档

| 文档 | 内容 |
|---|---|
| [项目简介](docs/introduction.md) | 目的、技术栈、运行步骤、重试分层、数据表 |
| [进度报告](docs/progress.md) | 路线图、已完成范围、测试进度、下一步、worker 并发决定 |
| [Agent 计划](docs/agent-plan.md) | 从 tool calling 到挂进现有 review job 的按天计划。未开始 |
| [测试与本地命令](docs/testing.md) | 用例清单、compose / pytest / npm test / curl |

## 运行拓扑

```mermaid
flowchart TB
  Browser["Browser"] --> Vercel["Vercel Next.js"]
  Vercel -->|"rewrite /api"| API["Northflank FastAPI"]
  GitHub["GitHub"] -->|"OAuth callback"| API
  GitHub -->|"webhook HMAC"| API

  API --> Neon[("Neon Postgres")]
  API --> Redis[("Upstash Redis")]
  API -->|"delay task"| AMQP["CloudAMQP RabbitMQ"]

  Cron["Northflank Cron / local Beat"] -->|"reclaim stale jobs"| AMQP
  AMQP --> Worker["Celery worker"]

  Worker --> Neon
  Worker -->|"PR files / Contents / blob"| GitHub
  Worker --> OpenRouter["OpenRouter"]

  Browser -->|"poll job / findings"| Vercel
```

步骤、三层重试和数据表见 [项目简介](docs/introduction.md)。

## 现在到哪了

登录、同步、手动 review、webhook 自动 review、两层幂等，以及 Vercel + Northflank + CloudAMQP 的 0 成本部署已经完成。9D 评论暂缓。11A-3（超限再拆 pack）取消。Review 仍是一次性 chat，没有 tool calling。Agent 未开始，计划在 [Agent 计划](docs/agent-plan.md)。

下一步：

1. 失败 pack 再审一轮，仍有缺口则 job 标 `partial`
2. 补测生产环境 `git push` 是否自动创建并完成 review job
3. 安全测试、UI polish、模型质量
4. 9D（暂缓）：findings 写回 GitHub PR 评论
5. Agent 从 Day 1 实验开始。Day 8 才用 feature flag 挂进现有 Celery job。现在不改队列，也不把开工定义成迁移 Taskiq

细节在 [进度报告](docs/progress.md)。自动化测试当前是后端 125 个、前端 30 个；用例清单和本地命令在 [测试与本地命令](docs/testing.md)，覆盖进度在进度报告里。
