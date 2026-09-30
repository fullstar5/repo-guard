# 测试与本地命令

[返回 README](../README.md) · [进度报告](progress.md)

自动化测试不连 GitHub、OpenRouter、Postgres 或 Redis。后端用 `unittest.mock` 和 `httpx.MockTransport`；前端用 Vitest 与 Testing Library，跑在 jsdom 里，没有浏览器 E2E。下面是仓库里已经存在的用例。做到哪一步、还缺什么，写在 [进度报告](progress.md)。compose、curl 以及生产环境手工检查仍在文末，它们不是自动化用例。

## Backend tests

在 `backend/` 执行 `pytest -q`。CI 的 backend job 跑同一条命令。当前 **122** 个用例，都在 `backend/test/`。

- **打包与窗口**（`test_diff_chunking.py`、`test_diff_chunking_edges.py`）：噪声过滤（大小写、后缀、`vendor/`、空文件名）；每个该审文件进入某个 pack；超大文件的余量进入后续 pack；hunk 带上下文；没有 patch 仍覆盖该文件；超长单行拆开而不是丢弃；预算是 `max_chars × 0.8`，下限为 1；纯删除 hunk 与默认行数；重叠窗口合并并裁到文件范围内；已删除文件用 patch，不用拉下来的源码；既无 patch 也无源码时记成缺口，不跳过；pack 前言要求 `file_path`，窗口不丢；`split_patch_by_hunks` 保留小 hunk、拆开过长 hunk。
- **GitHub 文件正文**（`test_github_pr_files.py`、`test_github_fetch_and_pagination.py`）：raw 200；Contents 403/404 回退到 blob；base64 JSON 解码；utf-8 的 `content` 字符串；空 body；非法 JSON 当文本；非对象 JSON 再 dump；Contents 500 不回退；blob 404 或缺少 URL 时返回 `None`。
- **分页**（`test_github_fetch_and_pagination.py`）：仓库列表和 PR 列表跟随 `Link` 的 `rel=next`，后续页丢掉 query 参数；响应不是 list 时抛 `TypeError`；PR files 只取第一页，响应里还有 next 也不继续。
- **同步落库**（`test_sync_services.py`）：解析带 `Z` 的时间和空值；仓库 upsert，并删除 GitHub 不再返回的仓库（空列表会删掉该用户全部本地仓库）；`replace_missing=True` 时删除缺失的 PR；webhook 风格的 `replace_missing=False` 不删其他 PR；空的 webhook 同步不再做后续 select；文件同步只 upsert，不删除 GitHub 已经不再列出的文件。
- **Review 执行**（`test_review_execution.py`、`test_review_job_idempotency.py`、`test_review_models.py`、`test_review_http_retries.py`）：小 PR 执行后 `total_chunks = 1`、状态 `completed`，summary 与 findings 入库，缺 `file_path` 会补上；创建时是 `pending` 且 `total_chunks = 0`；大 PR 的 `total_chunks` 等于 pack 数，summary 拼接，每个文件的 findings 都写入；部分 pack 失败时 job 仍是 `completed`，`error_message` 带失败信息，成功的 findings 保留；全部 pack 失败则标 `failed`；拉文件失败仍审 patch，并记下说明；源码和 patch 都缺时仍作为缺口送审；只有噪声文件则失败；不支持的 provider 标失败；执行过程中的 `SoftTimeLimitExceeded` 在这一层不标 `failed`；`execute_by_id` 跳过终态和缺失行；已有 active job 时复用、不新建；PR 消失时抛 `ValueError`；按 summary + suggestion 做空白和大小写去重，写入前去重；白名单模型通过，未知模型 `ValidationError`。OpenRouter HTTP：429 会重试 3 次，相邻尝试之间 sleep 35 秒；500 在等待一次后可以成功；`TimeoutError` 和 soft time limit 不重试。
- **任务重试与回收**（`test_review_job_task.py`、`test_review_reclaim_and_retries.py`）：第一次 soft timeout 整单重试且不标 `failed`，第二次标 `failed`；瞬时错误在次数用尽前重试，用尽后标 `failed`；非瞬时错误不重试，直接失败（空消息变成类型名）；countdown 从 5 秒翻倍，上限 300 秒；空白 `error_message` 会被换掉；job 不存在时相关标记返回空；reclaim 只更新查询返回的行（状态为 `processing`，且 `updated_at` 早于截止时间）并 commit，没有过期行则不 commit；Beat 任务会调用回收服务。
- **登录与 OAuth**（`test_http_api.py`、`test_oauth_openrouter_and_pipeline.py`）：JWT 往返，过期和垃圾 token 为 401；`/auth/me` 接受 Bearer 和 cookie，用户不存在为 401；没有 `sub` 为 401；非数字 `sub` 当前会抛出未处理的 `ValueError`；login 写入 state cookie，state 不匹配为 400；callback 写入 access cookie，logout 清掉它；authorize URL 带上 state 和 client；GitHub 错误体为 400；优先已验证的主邮箱，emails 403 时邮箱为 `None`；同一 GitHub 用户先插入再更新。
- **Webhook 与自动 review 流水线**（`test_webhook_idempotency.py`、`test_http_api.py`、`test_oauth_openrouter_and_pipeline.py`）：新 delivery 登记并 dispatch；相同 delivery 返回 200 且不 dispatch；发布失败删掉 delivery 并返回 503；`ping` 返回 200 且不登记；错误签名 401；非法 JSON 400；已处理事件缺少 `X-GitHub-Delivery` 为 400；`closed` 不处理；`opened` 会 dispatch。流水线：未知仓库、没有 token、已有 active job 时不新建；每个带 token 的本地仓库入队一个 job（没有 user 的行跳过）；入队失败把 job 标成 `failed` 并 commit；payload 没有 PR number 时不打开数据库。Celery 任务转到 `process_github_pull_request_event`。
- **HTTP 同步与 review**（`test_http_api.py`）：仓库同步没有 token 时 400，有 token 时返回 items；别人的仓库同步 PR 为 404，成功路径传入 `replace_missing=True`；文件同步没有 token 时 400；不属于当前用户的 PR、文件列表、单个文件为 404；创建 review 返回 202，并且 `delay` 一次；复用 active job 时不再 `delay`；入队失败返回 503，状态为 `failed`；列表、读取、创建在非所有者时为 404；未知模型 422；`GET /review-models` 返回白名单。
- **归属、限流、配置与健康检查**（`test_ownership_health_and_limits.py`、`test_rate_limit.py`、`test_production_baseline.py`）：review、PR、文件查询绑定调用者的 `user_id`；OAuth 限流对 IP 做哈希，原始 IP 不进 key；同步按 user、repository、pull request 分桶；review 按 user 和 PR 分桶；超限 429 且带 `Retry-After`；Redis 不可用时 503（fail closed）；关闭限流时不访问 Redis；`X-Forwarded-For` 只信配置的跳数；多条规则一次 `EVAL`，`retry-after` 向上取整，畸形返回值是 `RateLimitBackendError`。生产配置接受安全部署值，并拒绝 http、不安全 cookie、关闭限流、过短的 JWT / webhook secret、localhost 数据库和 rabbitmq 主机；非生产仍拒绝非正数的限流。liveness 不探活依赖；readiness 在只有 Redis 失败时降级仍返回 200，Postgres 失败时 503。
- **OpenRouter 结果解析**（`test_oauth_openrouter_and_pipeline.py`）：围栏 JSON；`blocker` 映射为 critical，`warning` 映射为 medium；对调的行号；布尔行号忽略；空 content 抛 `ValueError`；对象形式的 content 可解析；缺少 summary，或 findings 不是列表时拒绝。

## Frontend tests

在 `frontend/` 执行 `npm test`（即 `vitest run`）。CI 在 `tsc` 之后、`npm run build` 之前跑同一条命令。当前 **30** 个用例，都在 `frontend/test/`。

- **Job 钉选与 latest（Option A）**（`lib-behavior.test.ts`、`job-pin-and-sync-cache.test.tsx`）：非空 `jobId` 是历史钉选；默认选最新的 `completed`，否则选最新一条；钉选存在时用该 job，`resolveDisplayedReviewJob` 在 id 缺失时回退到 latest。切 tab、回到 latest、清掉钉选时去掉 `jobId` 和 finding，保留其他 query（`prJobHref` 得到 `?tab=review&jobId=2&q=keep`）。PR 页钉选时展示该 job 的 finding，不展示 latest；banner 为 “Viewing job #12”，Back to latest 链回最新 review；未钉选时展示最新 completed，且没有 Viewing banner；`jobId=99` 显示 not found，不展示别的 job 的 findings。文件页展示被钉选 job 在该文件上的 finding；未知钉选是 not-found，不借用别的 job。Run AI review 调用 `createReviewJob`（provider `openrouter`、model `openrouter/free`），使 review-jobs query 失效，并用 `router.replace` 写回 `?tab=review`。
- **Findings、状态与 diff**（`lib-behavior.test.ts`）：文件先按 id 再按 path 解析；href 带 `#L`；location 文案；`findingsForFile` 同时认 id 和 path。`completed` / `success` 映射为成功，`pending` 仍是 pending，未知状态（含 `partial`）映射为 failed。白名单模型有标签（Free router、Nemotron 3 Ultra），未知 id 原样保留。相对时间、时长、首字母用固定时钟。只有第一次 auth fetch 才算全屏等待。patch 分配新旧行号；`snippetAround` 取新文件一侧的窗口；只有带 `start_line` 的 finding 才高亮。
- **API client**（`api-client.test.ts`）：GitHub 登录 URL 来自公开 API base（`/api/auth/github/login`）；列表和 sync 解开 `items`；创建 review 的 POST body 带 `provider` 与 `model_name`。
- **同步按钮、job 表、会话**（`sync-and-jobs-ui.test.tsx`）：空闲时点击会调用 `onClick`；pending 时按钮禁用、`aria-busy`，文案是 “Syncing…”。空表有空状态；进行中的 job 显示 Queued，没有 Retry，选中行带钉选；终态显示时长（例如 `1:05`）和 Retry，模型标签为 Free router。登出清空 `["auth","me"]`。`Providers` 默认 `staleTime` 为 30000，`retry` 为 false。
- **同步写入 query cache**（`job-pin-and-sync-cache.test.tsx`）：首页 sync 用 POST 结果替换 `["repositories"]`，不重新请求列表；仓库页替换 `["repositories", id, "pull-requests"]`；PR 的 files 页替换 `["pull-requests", id, "files"]`。钉选时，其他 tab 的链接不含 `jobId`。

没有自动化覆盖的部分：compose 拉起、下面的 curl、浏览器里的完整 GitHub 登录，以及生产环境的 webhook Redeliver、手动 review、push 后自动建 job。

## 本地命令

后端命令在 `backend/` 下执行，Python 用 `backend/venv`。前端测试在 `frontend/`。

### 整套后端

```bash
cd backend
docker compose up -d --build
```

### 只起队列，本机热重载 API

```bash
cd backend
docker compose up -d rabbitmq worker beat
source venv/bin/activate
uvicorn app.main:app --reload
```

`compose.yaml` 里的 worker 已经带上 `--without-gossip --without-mingle --without-heartbeat`。不要另开一个本机 worker 去连同一个 broker，否则两条消费者会抢消息。

### 不通过 Compose 起 worker / beat

队列仍用 Compose 里的 RabbitMQ。Worker 并发与 `compose.yaml` 保持一致。

```bash
cd backend
source venv/bin/activate
docker compose up -d rabbitmq
celery -A app.core.celery_app:celery_app worker -l INFO --concurrency=2 --without-gossip --without-mingle --without-heartbeat
celery -A app.core.celery_app:celery_app beat -l INFO --schedule=/tmp/celerybeat-schedule
uvicorn app.main:app --reload
```

Beat 与 worker 分两个终端。生产不用常驻 Beat，由 Northflank Cron 发回收任务。

### 自动化测试

后端：

```bash
cd backend
source venv/bin/activate
pytest -q
```

前端（Node 20，与 CI 一致）：

```bash
cd frontend
npm ci
npm test
```

### 手工 API

把 `YOUR_ACCESS_TOKEN`、`REPO_ID`、`PR_ID`、`job_id` 换成实际值。浏览器登录走 cookie；下面的 curl 用 `Authorization` 头。

当前用户：

```bash
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

同步仓库：

```bash
curl -X POST http://localhost:8000/repositories/sync \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

同步某个仓库的 PR：

```bash
curl -X POST http://localhost:8000/repositories/REPO_ID/pr/sync \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

同步某个 PR 的 files：

```bash
curl -X POST http://localhost:8000/pull-requests/PR_ID/files/sync \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

创建 review job：

```bash
curl -X POST http://localhost:8000/pull-requests/PR_ID/review-jobs \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "openrouter",
    "model_name": "openrouter/free"
  }'
```

列出某个 PR 的 review jobs：

```bash
curl "http://localhost:8000/pull-requests/PR_ID/review-jobs" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

轮询单个 job：

```bash
curl "http://localhost:8000/review-jobs/JOB_ID" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```
