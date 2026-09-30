# 测试与本地命令

[返回 README](../README.md)

Step 7E 的 task 层失败路径和 Step 9C 的核心幂等路径已经用自动化测试锁住。Step 8 展示层目前以手工验证为主。结构化 review 在不同输入规模下的稳定性测试，以及 IDOR 测试，记在 [进度报告](progress.md) 的 Step 11。

## 已完成验证

- 小 PR 可走打包 review（能装进一个 pack 时 `total_chunks` 在执行后为 1；创建时为 0）
- `summary` 与 `findings` 可成功解析
- `summary` 与 `findings` 可成功写入数据库
- `review_jobs` 接口能够返回结构化结果
- compose 可启动 api / worker / beat / rabbitmq
- task 层第一次 soft timeout 会整单重试，不写 `failed`
- task 层第二次 soft timeout 会写回 `failed`
- task 层瞬时错误重试耗尽会写回 `failed`
- Beat reclaim task 会调用回收逻辑
- 前端 GitHub 登录 / 登出 / session 保持
- 前端仓库列表与 PR 列表，刷新走 GET 而不自动 sync GitHub
- 前端 PR 详情可触发 review 并轮询 `pending / processing / completed / failed`
- 点 review job 可展示该 job 的 summary 与 findings，过滤后列表会变
- 点 finding 可进入对应文件 diff 并定位行号；无效 `jobId` 显示 not found
- GitHub webhook HMAC 验签：错误签名 401；`ping` 与 `pull_request.synchronize` 返回 200
- 生产 webhook 改为 Northflank 公网 URL 后，GitHub Redeliver 返回 200
- 生产环境手动 Run AI review 可完成；Cron reclaim Job 可成功执行
- 本地：push 到已 sync 仓库的 PR 后，不点 Run AI review 也会自动出现 review job 并可以 `completed`（生产 push 路径待补测）
- 相同 `delivery_id` 重放返回 2xx 且不重复 dispatch；broker 发布失败会删除 delivery 记录以允许 GitHub 重试
- 同一 PR 已有 `pending` / `processing` job 时，手动与 webhook 入口复用已有 job，不重复创建或入队
- 噪声文件不进入 pack；无 patch 的业务文件仍生成窗口；大文件余量进入后续 pack
- 当前后端自动化测试共 39 个

## 仍建议补完的测试

集成路径，不阻塞已落地的打包。11A-3 已取消。

1. 小 PR 成功路径测试
   - 条件：过滤后的输入能装进一个 pack
   - 预期：`total_chunks = 1`
   - 预期：`status = completed`
   - 预期：`result_summary` 不为空
   - 预期：`findings` 可正常入库并随接口返回
2. 大 PR 打包路径测试
   - 条件：过滤噪声后仍超过一个 pack
   - 预期：`total_chunks` 等于 pack 次数（不是 hunk 数）
   - 预期：每个该审文件都出现在某个 pack 里
   - 预期：成功 pack 的 `summary` 会拼接进 `result_summary`
   - 预期：成功 pack 的 `findings` 会写入数据库
3. 部分成功测试
   - 条件：部分 pack 成功，部分失败
   - 预期：整个 review job 仍可 `completed`
   - 预期：`error_message` 中包含失败信息
   - 预期：数据库中保留成功 pack 产出的 findings
4. 全部 pack 失败测试
   - 条件：所有 pack 都失败
   - 预期：整个 review job 标记为 `failed`
   - 预期：`error_message` 中包含失败原因汇总
5. 去重、路径补全与忽略名单测试
   - 条件：lockfile 等噪声文件在 diff 里；不同 pack 产出重复 findings，或 finding 缺少 `file_path`
   - 预期：噪声文件不进入任何 pack
   - 预期：重复 findings 会被去重
   - 预期：pack 内缺失的 `file_path` 会被 fallback 补齐

打包单测已覆盖无 skip / 上下文 / 无 patch。展示层已可消费已稳定的小 PR 成功路径。

## 本地命令

命令都在 `backend/` 下执行。Python 用 `backend/venv`。

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

```bash
cd backend
source venv/bin/activate
pytest -q
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
