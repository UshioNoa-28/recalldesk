"""全局配置。所有配置都可以通过 .env 文件或环境变量覆盖。"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- PostgreSQL：文档元数据 ----
    database_url: str = "postgresql+asyncpg://rag:rag@127.0.0.1:5435/anna_rag"

    # ---- Redis Stream：任务队列（文档索引 / Eval 出题各一条 stream）----
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_document_task_stream: str = "anna_rag_document_tasks"
    redis_document_consumer_group: str = "anna_rag_document_workers"
    redis_eval_task_stream: str = "anna_rag_eval_tasks"
    redis_eval_consumer_group: str = "anna_rag_eval_workers"
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

    # ---- Qdrant：向量 ----
    qdrant_url: str = "http://127.0.0.1:6335"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "anna_rag_documents"
    qdrant_embedding_dim: int = 1024
    # 服务端 BM25 推理（.env 里用 JSON 覆盖 options）
    qdrant_bm25_model: str = "Qdrant/bm25"
    qdrant_bm25_options: dict[str, str] = {"tokenizer": "multilingual"}

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
