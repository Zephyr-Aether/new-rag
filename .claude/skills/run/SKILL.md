---
name: run
description: 启动并驱动这个 Agent 平台应用（FastAPI/uvicorn，mock provider + SQLite，无需外部依赖）。
---

# Run: Agent Platform（FastAPI + React 控制台）

## 启动

后台启动（无需外部依赖：默认 `dev.db` + mock provider，无 API key）：

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning > /tmp/api.log 2>&1 &
```

前端是产品化 React SPA，构建后由后端托管在 `/`（`open http://localhost:8000/`）。开发模式热更新：

```bash
cd frontend && npm run dev    # :5173，代理到 :8000
```

端口冲突（如旧实例占用）时，先精确停掉旧的 uvicorn 监听者（只停 uvicorn，勿误杀同端口其他进程）：

```bash
lsof -ti:8000 -sTCP:LISTEN | while read p; do
  ps -o command= -p "$p" | grep -q uvicorn && kill "$p"
done
```

## 就绪探测

```bash
for i in $(seq 1 20); do curl -sf http://127.0.0.1:8000/health/live > /dev/null && break; sleep 0.5; done
curl -s http://127.0.0.1:8000/health/ready   # {"status":"ready"}
curl -s http://127.0.0.1:8000/health/ha      # 实例身份/region/队列水位
```

## 驱动冒烟

```bash
B=http://127.0.0.1:8000
# 对话 run（mock 算 12+30）
curl -s -X POST $B/agents/runs -H 'Content-Type: application/json' -d '{"input":"12 + 30"}'
# 工具全管线
curl -s -X POST $B/tools/calc.add/execute -H 'Content-Type: application/json' -d '{"args":{"a":2,"b":5}}'
# 知识库入库 + 检索
curl -s -X POST $B/knowledge/documents -H 'Content-Type: application/json' \
  -d '{"document_id":"doc-1","title":"退货政策","text":"## 退款到账时间\n退款 3-5 个工作日到账。"}'
curl -s -X POST $B/knowledge/search -H 'Content-Type: application/json' -d '{"query":"退款到账"}'
# 发布生命周期（seed agent_id 从 run 响应取）
AGENT=<agent_id>
curl -s -X POST $B/agents/$AGENT/versions -H 'Content-Type: application/json' -d '{"system_prompt":"v2"}'
curl -s -X POST $B/agents/$AGENT/versions/2/contract-check      # §58 十项契约报告
curl -s -X POST $B/agents/$AGENT/versions/2/publish -H 'Content-Type: application/json' -d '{"force":true}'
# 事件 Outbox 幂等 + DLQ
curl -s -X POST $B/events/publish -H 'Content-Type: application/json' -d '{"event_type":"demo.hello","dedupe_key":"d1"}'
curl -s "$B/queue/jobs?state=DEAD_LETTER"
```

## 停止

```bash
lsof -ti:8000 -sTCP:LISTEN | xargs -r kill
```

## 说明

- 环境变量：`APP_DATABASE_URL`（默认 `sqlite+aiosqlite:///./dev.db`）、`APP_LLM_PROVIDER`（默认 `mock`，接真 LLM 设 `openai` + base_url/key）。
- 异步 run：`{"await_result": false}` 入队，轮询 `GET /agents/runs/{id}` 到 `COMPLETED`。
- 测试：`make test`（237 个）；混沌/评测/压测脚本：`make chaos` / `scripts/eval.py` / `scripts/bench_load.py`。
