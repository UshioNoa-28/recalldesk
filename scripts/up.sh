#!/usr/bin/env bash
# 起全栈：postgres/redis → 灌 schema（幂等）→ ollama + 模型 → 其余服务 → 健康检查
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose up -d --wait postgres redis
# 新卷首次启动时 entrypoint 用临时实例跑初始化，健康检查会提前通过；
# 临时实例关停、真实例起来之间 psql 会撞上 "database system is shutting down"。
# schema 幂等，失败就重试，直到真实例接住连接。
for attempt in $(seq 1 30); do
  if docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U rag -d anna_rag < db/schema.sql >/dev/null 2>&1; then
    break
  fi
  [ "$attempt" -lt 30 ] || { echo "schema 灌入失败" >&2; docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U rag -d anna_rag < db/schema.sql; exit 1; }
  sleep 2
done

docker compose up -d --wait ollama
for model in "$(grep -E '^EMBEDDING_MODEL=' .env | cut -d= -f2-)" \
             "$(grep -E '^RERANK_MODEL=' .env | cut -d= -f2-)"; do
  [ -n "$model" ] || continue
  docker compose exec -T ollama ollama list | awk 'NR>1{print $1}' | grep -qxF "$model" \
    || docker compose exec -T ollama ollama pull "$model"
done

docker compose up -d --wait --build
curl -fsS http://127.0.0.1:8001/health
