"""配置默认值测试（不读 .env，避免本机环境干扰）。"""

from __future__ import annotations

from unittest import TestCase

from settings import Settings


class SettingsDefaultsTests(TestCase):
    def test_task_queue_defaults(self) -> None:
        settings = Settings(_env_file=None)

        self.assertEqual(10_000, settings.redis_stream_maxlen)
        self.assertEqual("0-0", settings.redis_claim_start_id)
        self.assertEqual(60_000, settings.redis_claim_min_idle_ms)
        self.assertEqual(10, settings.task_max_attempts)

    def test_embedding_defaults(self) -> None:
        settings = Settings(_env_file=None)

        self.assertEqual("mxbai-embed-large:latest", settings.embedding_model)
        self.assertEqual(512, settings.chunk_size)
        self.assertEqual(64, settings.chunk_overlap)

    def test_qdrant_defaults(self) -> None:
        settings = Settings(_env_file=None)

        self.assertEqual(1024, settings.qdrant_embedding_dim)
        self.assertEqual("Qdrant/bm25", settings.qdrant_bm25_model)
        self.assertEqual({"tokenizer": "multilingual"}, settings.qdrant_bm25_options)


if __name__ == "__main__":
    import unittest

    unittest.main()
