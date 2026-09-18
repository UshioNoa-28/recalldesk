# RecallDesk

混合检索 RAG 服务：上传文档 → 分块 → embedding → Neo4j 混合检索（HNSW 向量语义 + Lucene 全文 BM25，RRF 融合），可选查询改写与本地 Ollama 重排；附带离线检索评测（recall@k / MRR）与 Web 控制台。

技术栈：FastAPI / PostgreSQL（元数据 + Outbox）/ Redis Stream（任务队列）/ Neo4j（检索索引，后续知识图谱）/ React + Vite。

支持格式：`.txt / .md / .csv / .json / .pdf`（PDF 走 pypdf 提取文本层，纯扫描件会被拒绝）。

## 部署（Docker）

前置：Docker，以及本机 Ollama 拉好两个模型：

```bash
ollama pull mxbai-embed-large
ollama pull dengcao/Qwen3-Reranker-4B:Q4_K_M
```

准备配置（查询改写需要 OpenAI 兼容 LLM，按注释填；重排走本机 Ollama）：

```bash
cp .env.example .env
```

启动：

```bash
docker compose up -d
```

- 控制台：http://127.0.0.1:5173
- API：http://127.0.0.1:8001（Swagger 文档在 `/docs`）

## 本地开发

```bash
docker compose up -d postgres redis neo4j   # 只起基础设施
pip install -e .

uvicorn app.main:app --reload                 # API
python -m app.publisher.document            # 以下六个 worker 各开一个终端
python -m app.consumer.document
python -m app.publisher.eval
python -m app.consumer.eval
python -m app.publisher.eval_run
python -m app.consumer.eval_run
python -m app.publisher.graph   # 知识图谱抽取链路（GRAPH_ENABLED=false 时可不起）
python -m app.consumer.graph
```

## 快速试用

```bash
curl -X POST http://127.0.0.1:8001/documents -F 'file=@./a.txt'   # 上传（后台异步索引）
curl 'http://127.0.0.1:8001/search?q=苹果有什么营养&top_k=3'       # 混合检索
```
