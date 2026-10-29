from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """模型网关的全部可调项；env 名与 .env.example 的键逐条同名（大小写不敏感）。"""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    # Ollama 只在这一个服务里出现，Java 侧不再认识它
    ollama_base_url: str = "http://127.0.0.1:11434"

    embedding_model: str = "qwen3-embedding:0.6b"
    embedding_dim: int = 1024
    embedding_batch_size: int = 32
    embedding_timeout_seconds: float = 120.0

    rerank_model: str = "dengcao/Qwen3-Reranker-0.6B:Q8_0"
    rerank_candidate_chars: int = 500
    rerank_num_ctx: int = 4096
    rerank_top_logprobs: int = 20
    rerank_concurrency: int = 1
    rerank_timeout_seconds: float = 180.0
    rerank_keep_alive: str = "1h"

    # 留空则 /rewrite 回 503：Java 默认会走改写路，没配就别开这一路
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_temperature: float = 0.0
    llm_timeout_seconds: float = 120.0
    llm_extra_body: str = ""

    rewrite_n_variants: int = 3

    @property
    def ollama_root(self) -> str:
        return self.ollama_base_url.rstrip("/")

    @property
    def rewrite_enabled(self) -> bool:
        return bool(self.llm_base_url.strip() and self.llm_model.strip())

    @property
    def rerank_enabled(self) -> bool:
        return bool(self.rerank_model.strip())


settings = Settings()
