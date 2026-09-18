"""全局配置。所有配置都可以通过 .env 文件或环境变量覆盖。"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- PostgreSQL：文档元数据 ----
    database_url: str = "postgresql+asyncpg://rag:rag@127.0.0.1:5435/anna_rag"

    # ---- Redis Stream：任务队列（文档索引 / Eval 出题 / Eval 逐题评测各一条 stream）----
    # 6380 对应 docker-compose.yml 的宿主机映射（6379 被本机其它 Redis 占用）
    redis_url: str = "redis://127.0.0.1:6380/0"
    redis_document_task_stream: str = "anna_rag_document_tasks"
    redis_document_consumer_group: str = "anna_rag_document_workers"
    redis_eval_task_stream: str = "anna_rag_eval_tasks"
    redis_eval_consumer_group: str = "anna_rag_eval_workers"
    redis_eval_run_task_stream: str = "anna_rag_eval_run_tasks"
    redis_eval_run_consumer_group: str = "anna_rag_eval_run_workers"
    redis_stream_maxlen: int = 10_000
    redis_claim_min_idle_ms: int = 60000
    redis_claim_start_id: str = "0-0"

    # ---- 后台任务 ----
    task_publish_interval_seconds: float = 0.5
    task_publish_batch_size: int = 50
    task_max_attempts: int = 10
    # 失败重试的指数退避基数：第 n 次失败后等待 base * 2^(n-1) 秒再重投
    task_retry_backoff_base_seconds: float = 30.0

    # ---- Eval 出题任务 ----
    eval_task_publish_interval_seconds: float = 2.0
    eval_task_publish_batch_size: int = 20
    eval_task_max_attempts: int = 5
    eval_task_retry_backoff_base_seconds: float = 30.0

    # ---- Eval 逐题任务（一次 run fan-out 出来的检索评测任务）----
    # 一次任务 = 一次检索，比出题便宜得多：投递更勤、重试预算更小。
    # 超限该题标 failed，run 由 finalize 收尾成 failed 而不是永远挂着
    eval_run_task_publish_interval_seconds: float = 1.0
    eval_run_task_publish_batch_size: int = 50
    eval_run_task_max_attempts: int = 3
    eval_run_task_retry_backoff_base_seconds: float = 10.0

    # ---- Neo4j：chunk 检索索引（HNSW 向量 + Lucene 全文），未来的图也住这里 ----
    # 7688/7475：宿主机 7687/7474 已被本机另一套 Neo4j 占用，错开映射（compose 同步）
    neo4j_uri: str = "bolt://127.0.0.1:7688"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "recalldesk"  # noqa: S105 -- 个人本地 compose 的缺省口令，同 PG 的 rag/rag 性质
    embedding_dim: int = 1024  # 换 embedding 模型要同步改（启动时校验索引维度）
    chunk_fulltext_analyzer: str = "cjk"  # 中文二分词；换分词后 sparse 基线要重跑

    # ---- Embedding（默认指向本机 Ollama 的 OpenAI 兼容接口）----
    embedding_model: str = "mxbai-embed-large:latest"
    embedding_base_url: str = "http://127.0.0.1:11434/v1"
    embedding_api_key: str = "ollama"

    # ---- LLM（OpenAI 兼容中转；query rewrite 等检索侧功能使用，留空则不可用）----
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_temperature: float = 0.0
    llm_timeout: float = 120.0
    # 中转/模型级私有参数透传（思考型模型常需 {"enable_thinking": false} 以免思考文本污染 JSON）
    llm_extra_body: dict[str, object] = {}
    query_rewrite_enabled: bool = False

    # ---- Rerank（Ollama 上的 Qwen3-Reranker，生成式重排：judge prompt + logprobs）----
    rerank_enabled: bool = False
    rerank_top_n: int = 20           # 重排前保留多少候选
    rerank_candidate_chars: int = 500  # 每个候选截断到多少字符，控制 token
    rerank_ollama_url: str = "http://127.0.0.1:11434"
    rerank_model: str = "dengcao/Qwen3-Reranker-4B:Q4_K_M"
    rerank_num_ctx: int = 4096       # 模型默认 40K context 会吃 ~9GB 内存，压一压
    rerank_timeout_seconds: float = 60.0
    rerank_concurrency: int = 2      # llama-server 每个并发请求独立 KV cache，高了 OOM

    # ---- 知识图谱（第三路召回 + 文档抽取任务链，默认关）----
    graph_enabled: bool = False
    graph_hops: int = 2                # 扩展最大跳数（1~3 之间被 clamp）
    graph_candidates: int = 20         # 图频道每轮最多贡献的候选块数
    graph_link_min_score: float = 0.72   # 向量链接余弦下限（实测噪音带 0.69 之上；<=0 关闭该路）
    graph_extract_concurrency: int = 2  # 抽取时的 LLM 并发闸
    redis_graph_task_stream: str = "anna_rag_graph_tasks"
    redis_graph_consumer_group: str = "anna_rag_graph_workers"
    graph_task_publish_interval_seconds: float = 1.0
    graph_task_publish_batch_size: int = 20
    graph_task_max_attempts: int = 5
    graph_task_retry_backoff_base_seconds: float = 30.0

    # ---- 分块参数 ----
    chunk_size: int = 512
    chunk_overlap: int = 64

    # ---- 检索默认返回数量 ----
    top_k: int = 5

    # ---- 上传限制 ----
    max_file_size_bytes: int = 10 * 1024 * 1024  # 10 MiB
    allowed_extensions: str = ".txt,.md,.csv,.json,.pdf"

    # ---- 本地数据目录（原始文件）----
    data_dir: str = "data"


settings = Settings()
