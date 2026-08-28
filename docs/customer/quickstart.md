# 快速开始 · 10 分钟跑通第一次价值

目标：从零到「跑通一条会检索你自己知识的对话，并看到它的运行与发布过程」。全程约 10 分钟。

## 1. 起服务（官方推荐拓扑）

```bash
# 仓库根目录
export APP_AUTH_JWT_SECRET="$(openssl rand -hex 32)"   # prod 安全门禁必需，强随机
docker compose up -d --build
curl -sf http://localhost:8000/health/ready            # {"status":"ready"}
```

浏览器打开 `http://localhost:8000/`（本地模式为 HTTP；绑定域名后由 Caddy 自动上 TLS，见[部署手册](deployment.md)）。

> 无 Docker 的开发模式：`.venv/bin/uvicorn app.main:app --port 8000`（SQLite + mock LLM，零外部依赖）。

## 2. 首次登录

seed 身份：租户 `tenant-default` / 用户 `user-default`，首次登录会**强制改密**。

登录后进入「快速开始」引导（在应用内按步骤走完即可）：

**接模型 → 导入知识 → 发起对话 → 看运行与复盘 → 发布与治理**

## 3. 五步价值闭环（产品内引导的完整版）

| 步骤 | 做什么 | 在哪 |
|---|---|---|
| 接模型 | 当前默认 mock（本地确定性）。接真实模型：到「管理员区 → 配置中心 → 模型接入」填 Provider / 模型 / base_url / API key，保存即生效 | 配置中心 |
| 导入知识 | 到「知识」页建库、上传第一篇文档（Markdown / 文本，上传即入库） | 知识库 |
| 发起对话 | 到「对话」页提问，实时看到工具调用与检索引用 | 对话 |
| 看运行 | 进 Run 详情：步骤时间线、模型、工具/检索引用、成本、(失败时)错误原因；可 Replay / Compare | 运行 |
| 发布版本 | 到「发布」页创建/灰度版本：契约检查 → 基准回归 → Canary → 全量，随时回滚 | 发布 |

**建议的第一条对话**：先导入了一段自己的资料后，问「**XX 政策里……是怎么说的？**」。回答下方会出现「引用来源」，点击可跳转原文档——这是判断"是否真的用上了你的知识"的最快方式。

## 4. 一个 60 秒 API 冒烟（验证后端健康）

```bash
B=http://localhost:8000
# mock 下直接可用；真实环境先取 token：
# POST /auth/token  {"tenant_id":"tenant-default","user_id":"user-default","password":"<client_sha256(明文)>"}
curl -s -X POST $B/agents/runs -H 'Content-Type: application/json' -d '{"input":"12 + 30"}'
```

返回 `run_id` 后：

```bash
curl -s $B/agents/runs/$run_id   # {"run":{"state":"COMPLETED", ...}, "steps":[...]}
```

## 5. 常用入口速查

- 控制台首页（工作台）：4 个高频动作 + 最近运行 +（管理职能）待办
- 运行复盘：`/runs`；对话：`/chat`；知识：`/knowledge`；发布：在「发布·版本」
- 管理员区（管理职能可见）：用户/权限/审计/数据生命周期/队列/事件/配置中心

## 下一步

- 想上生产：见[部署手册](deployment.md)的生产启动清单
- 想接入别的系统：见[集成指南](integration-guide.md)
- 想让发布不被质量回退打脸：到「知识 → 评测」录入黄金集/坏案例，发布时会自动跑基准回归并阻断回退（[故障排查](troubleshooting.md)里解释了公共报错）