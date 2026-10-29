class UpstreamError(Exception):
    """下游（Ollama / LLM）返回了不可用的响应。"""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class NotConfiguredError(Exception):
    """能力未配置：Java 侧理论上不会调用，真调到了就明确回 503。"""
