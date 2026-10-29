# RecallDesk

多用户的混合召回检索服务 + 离线评测台：上传文档 → 切块 → embedding → PostgreSQL 双路召回
（pgvector HNSW 稠密 + ParadeDB pg_search BM25 稀疏，RRF 融合），可选 LLM 查询改写与本地
Ollama 重排；用户自带题目（原文片段作证据）上传即可跑评测、看指标、逐路调参做消融。
**只做检索，不做答案生成。**

技术栈：Java 21（虚拟线程）/ Spring Boot 3.5 / MyBatis-Plus / Maven 多模块
/ PostgreSQL（pgvector + ParadeDB pg_search）/ Redis Streams / Ollama / Docker Compose
/ React + Vite。模型调用统一走 Python 网关（FastAPI + LangChain），Java 只认一个
`MODEL_SERVICE_URL`；鉴权为自写 JWT 过滤器，不引入 Spring Security。

支持格式：`.txt` / `.md`（严格 UTF-8）。

## 部署（Docker）

前置：Docker（当前用户在 `docker` 组里，或全程 `sudo`）。Ollama 也跑在 compose 里，模型存在
`ollama_models` 卷中，首次启动自动拉取。

准备配置（一次性）：

```bash
cp .env.example .env
# 必填：JWT_SECRET（32 字节以上）、MAIL_FROM / SMTP_USERNAME / SMTP_PASSWORD
# （注册要邮箱验证码；缺 MAIL_FROM 时 api 启动即失败，不是运行期才报错）
```

启动：

```bash
./scripts/up.sh
```

脚本做的事：起 postgres/redis → 灌 `db/schema.sql`（全部 `IF NOT EXISTS`，可重复执行）
→ 拉 `.env` 里配了但卷里没有的 Ollama 模型 → 构建并启动全栈 → 等 healthcheck 通过。

- 控制台：http://127.0.0.1:5173
- API：http://127.0.0.1:8001（健康检查 `/health`）
- 模型网关：http://127.0.0.1:8002（健康检查 `/health`）

> 注意：`dengcao/Qwen3-Reranker-0.6B:Q8_0` 实测任何输入都输出 `"3"`（首 token 没有 yes/no），
> 此时重排分全为 0、检索仍可用但没有重排效果。若日志出现这条告警，请换一个能输出 yes/no
> 的 rerank 模型，或把 `RERANK_MODEL` 留空关闭重排。

## 本地开发

```bash
docker compose up -d postgres redis ollama model   # 只起基础设施、Ollama 与模型网关（模型按部署步骤拉一次）
docker compose exec -T postgres psql -U rag -d anna_rag < db/schema.sql   # 幂等，可重复执行

cd backend
mvn -B -o test                        # 全量单测（离线）
mvn -B -o -pl interfaces -am package  # 打可执行 jar
```

模型网关也可以脱离 compose 直接跑：

```bash
cd model-service
python -m venv .venv && . .venv/bin/activate
pip install -e '.[test]'
uvicorn app.main:app --port 8002
pytest                                # 离线单测，不需要 Ollama
```

一个进程一类角色，同一个 jar 换一个属性（对应 compose 里的五个服务）：

```bash
java -jar interfaces/target/recalldesk-interfaces-*.jar                                   # web 服务
java -jar interfaces/target/recalldesk-interfaces-*.jar --recalldesk.worker.role=document-publisher
java -jar interfaces/target/recalldesk-interfaces-*.jar --recalldesk.worker.role=document-consumer
java -jar interfaces/target/recalldesk-interfaces-*.jar --recalldesk.worker.role=eval-run-publisher
java -jar interfaces/target/recalldesk-interfaces-*.jar --recalldesk.worker.role=eval-run-consumer
```

`db/schema.sql` 是 schema 的唯一真相源：没有迁移工具，改 schema 就改这个文件并重建库。

## 快速试用

```bash
# 注册需要邮箱验证码：先发码，再带码注册
curl -X POST http://127.0.0.1:8001/auth/email-code -H 'Content-Type: application/json' \
     -d '{"email":"you@example.com"}'
curl -X POST http://127.0.0.1:8001/auth/register -H 'Content-Type: application/json' \
     -d '{"username":"alice","password":"s3cret-pass","email":"you@example.com","code":"123456"}'

TOKEN=<上一步返回的 access_token>
curl -X POST http://127.0.0.1:8001/documents -H "Authorization: Bearer $TOKEN" -F 'file=@./a.txt'
curl "http://127.0.0.1:8001/search?q=苹果有什么营养&top_k=3" -H "Authorization: Bearer $TOKEN"
```

## 模块

| 模块 | 内容 |
| --- | --- |
| `domain` | 纯领域：文档/评测集/run 的状态机与值对象、指标口径、端口接口（`port.{persistence,queue,model,auth,ops}`）、异常（`exception`）。零框架依赖 |
| `application` | 用例编排：上传/索引/检索/评测/开跑、出箱 publisher 与 worker consumer、幂等键、账号与验证码 |
| `infrastructure` | 端口实现：MyBatis-Plus 仓储、Redis Stream 队列与验证码/限流/幂等存储、模型网关客户端（手写 HTTP）、本地文件存储、SMTP |
| `interfaces` | 唯一组合根：`@Configuration` 装配、HTTP 路由、JWT/限流过滤器、错误信封 |
| `model-service` | Python 网关（FastAPI + LangChain）：`/embed`、`/rerank`、`/rewrite`，对接 Ollama 与可选 OpenAI 兼容 LLM |
