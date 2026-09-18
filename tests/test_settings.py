"""配置默认值测试（不读 .env，避免本机环境干扰）。"""

from __future__ import annotations

import os
from unittest import TestCase

from settings import Settings


def _isolated() -> Settings:
    """默认值测试必须隔掉宿主环境：shell 里 export 过的同名变量会盖掉默认值。"""

    blocked = {key.upper() for key in Settings.model_fields}
    env = {k: v for k, v in os.environ.items() if k.upper() not in blocked}
    from unittest.mock import patch

    with patch.dict(os.environ, env, clear=True):
        return Settings(_env_file=None)


class SettingsDefaultsTests(TestCase):
    def test_task_queue_defaults(self) -> None:
        settings = _isolated()

        self.assertEqual(10_000, settings.redis_stream_maxlen)
        self.assertEqual("0-0", settings.redis_claim_start_id)
        self.assertEqual(60_000, settings.redis_claim_min_idle_ms)
        self.assertEqual(10, settings.task_max_attempts)

    def test_embedding_defaults(self) -> None:
        settings = _isolated()

        self.assertEqual("mxbai-embed-large:latest", settings.embedding_model)
        self.assertEqual(512, settings.chunk_size)
        self.assertEqual(64, settings.chunk_overlap)

    def test_neo4j_defaults(self) -> None:
        settings = _isolated()

        self.assertEqual(1024, settings.embedding_dim)
        self.assertEqual("bolt://127.0.0.1:7688", settings.neo4j_uri)
        self.assertEqual("cjk", settings.chunk_fulltext_analyzer)


if __name__ == "__main__":
    import unittest

    unittest.main()
