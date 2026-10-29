BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE EXTENSION IF NOT EXISTS pg_search;

CREATE TABLE IF NOT EXISTS users (
    id character varying(36) NOT NULL,
    -- 注册时一律转小写入库，所以这个唯一约束天然大小写不敏感，不必建表达式索引
    username character varying(64) NOT NULL,
    password_hash text NOT NULL,
    -- 注册时经验证码确认过的邮箱（归一为小写）。邮箱上线之前的老账号为 NULL，
    -- PostgreSQL 的唯一约束不拦 NULL，所以「加邮箱之前的数据」天然兼容这一列
    email character varying(254),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT users_pkey PRIMARY KEY (id),
    -- password_hash 存 PBKDF2 的自描述编码串（含迭代次数与盐），长度用不上约束，但别让它空着进去
    CONSTRAINT users_username_not_blank CHECK (username <> ''),
    CONSTRAINT users_email_not_blank CHECK (email IS NULL OR email <> '')
);

-- 一个邮箱只能被一个账号占用；NULL 不参与唯一性（老账号共存）
CREATE UNIQUE INDEX IF NOT EXISTS users_email_key ON users USING btree (email) WHERE email IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS users_username_key ON users USING btree (username);

CREATE TABLE IF NOT EXISTS documents (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    name character varying(255) NOT NULL,
    storage_key character varying(1024) NOT NULL,
    size_bytes bigint NOT NULL,
    media_type character varying(255),
    status character varying(16) DEFAULT 'pending' NOT NULL,
    chunk_count integer,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    indexed_at timestamp with time zone,
    CONSTRAINT documents_pkey PRIMARY KEY (id),
    CONSTRAINT documents_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_documents_user_created ON documents USING btree (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS document_tasks (
    id character varying(36) NOT NULL,
    document_id character varying(36) NOT NULL,
    status character varying(16) DEFAULT 'pending' NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    last_error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    queued_at timestamp with time zone,
    next_retry_at timestamp with time zone,
    CONSTRAINT document_tasks_pkey PRIMARY KEY (id),
    CONSTRAINT document_tasks_document_id_fkey
        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_document_tasks_document_id ON document_tasks USING btree (document_id);

CREATE INDEX IF NOT EXISTS ix_document_tasks_status ON document_tasks USING btree (status);

CREATE TABLE IF NOT EXISTS eval_testsets (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    name character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT eval_testsets_pkey PRIMARY KEY (id),
    CONSTRAINT eval_testsets_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_eval_testsets_user_created ON eval_testsets USING btree (user_id, created_at DESC);

-- 题目由用户直接上传，进来就是终态：没有异步出题，也就没有 status / error_message 这两列。
CREATE TABLE IF NOT EXISTS eval_testset_items (
    id character varying(36) NOT NULL,
    testset_id character varying(36) NOT NULL,
    query text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT eval_testset_items_pkey PRIMARY KEY (id),
    CONSTRAINT eval_testset_items_testset_id_fkey
        FOREIGN KEY (testset_id) REFERENCES eval_testsets(id) ON DELETE CASCADE,
    CONSTRAINT eval_testset_items_query_not_blank CHECK (btrim(query) <> '')
);

CREATE INDEX IF NOT EXISTS ix_eval_testset_items_testset_id ON eval_testset_items USING btree (testset_id);

-- 一行 = 一个金标 chunk。
CREATE TABLE IF NOT EXISTS eval_testset_item_evidence (
    id character varying(36) NOT NULL,
    item_id character varying(36) NOT NULL,
    document_id character varying(36) NOT NULL,
    -- 第几块。金标就是这一块，不做任何文本匹配：chunk_index 是用户直接指定的唯一答案
    chunk_index integer NOT NULL,
    ordinal integer DEFAULT 0 NOT NULL,
    CONSTRAINT eval_testset_item_evidence_pkey PRIMARY KEY (id),
    CONSTRAINT uq_eval_evidence_item_ordinal UNIQUE (item_id, ordinal),
    CONSTRAINT eval_testset_item_evidence_item_id_fkey
        FOREIGN KEY (item_id) REFERENCES eval_testset_items(id) ON DELETE CASCADE,
    -- 删文档时由应用层显式处理证据（报「出处失效」而不是让级联静默改分母），所以 RESTRICT
    CONSTRAINT fk_evidence_document
        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE RESTRICT,
    CONSTRAINT eval_evidence_chunk_index_non_negative CHECK (chunk_index >= 0)
);

CREATE INDEX IF NOT EXISTS ix_eval_testset_item_evidence_document_id ON eval_testset_item_evidence USING btree (document_id);

CREATE INDEX IF NOT EXISTS ix_eval_evidence_item_id ON eval_testset_item_evidence USING btree (item_id);

CREATE TABLE IF NOT EXISTS eval_runs (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    testset_id character varying(36) NOT NULL,
    status character varying(16) DEFAULT 'running' NOT NULL,
    config_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    metrics_json jsonb,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    CONSTRAINT eval_runs_pkey PRIMARY KEY (id),
    CONSTRAINT eval_runs_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT eval_runs_testset_id_fkey
        FOREIGN KEY (testset_id) REFERENCES eval_testsets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_eval_runs_testset_id ON eval_runs USING btree (testset_id);

CREATE INDEX IF NOT EXISTS ix_eval_runs_user_created ON eval_runs USING btree (user_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_eval_runs_running_per_testset ON eval_runs USING btree (testset_id) WHERE (status = 'running');

-- 检索块：text 是可丢弃的派生副本，真权威是磁盘原件 + reindex 链路。
--
-- user_id 是刻意冗余下来的一份归属（documents 上也有）。不这么做的替代方案是检索 SQL
-- join documents 再过滤，但那样归属谓词就到不了索引里：pg_search 的 TopK 扫描会先按
-- BM25 取满 limit 再交给外层过滤，用户实际拿到的条数少于 limit——「双路召回某路只回 2 条」
-- 这种诡异现象就是这么来的。user_id 进 bm25 索引后它变成扫描内的 heap_filter（always_filters），
-- TopK 在过滤后的候选上继续取满，语义才对。
CREATE TABLE IF NOT EXISTS chunks (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    doc_id text NOT NULL,
    user_id text NOT NULL,
    chunk_index integer NOT NULL,
    document_name text NOT NULL,
    chunk_count integer,
    text text NOT NULL,
    embedding vector(1024),
    CONSTRAINT chunks_doc_key UNIQUE (doc_id, chunk_index),
    -- 文档删除即删块：删除是确定性操作，请求事务里直接级联完成，不经过 worker
    CONSTRAINT chunks_doc_id_fkey FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
);

-- hnsw.iterative_scan 默认 off：带 WHERE 的向量 TopK 会在索引扫不满时直接少给结果。
-- 本项目的连接池用 Hikari connection-init-sql 把它设成 relaxed_order（见 application.yml），
-- 启动期 ChunkIndexStartupCheck 会核对，忘了配就启动失败而不是悄悄掉召回。
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);

-- user_id 用 raw 分词：它是身份标识不是待检索文本，切词只会制造假命中。
CREATE INDEX IF NOT EXISTS chunks_text_bm25 ON chunks USING bm25 (id, text, user_id) WITH (text_fields =
    '{"text": {"tokenizer": {"type": "chinese_compatible"}}, "user_id": {"tokenizer": {"type": "raw"}}}');

CREATE TABLE IF NOT EXISTS eval_run_items (
    id character varying(36) NOT NULL,
    run_id character varying(36) NOT NULL,
    testset_item_id character varying(36) NOT NULL,
    hit_rank integer,
    latency_ms double precision DEFAULT 0::double precision NOT NULL,
    -- 分母是「引文段数」而不是「块数」：一段话跨两块不算两个必中目标
    evidence_total integer DEFAULT 1 NOT NULL,
    evidence_matched integer DEFAULT 0 NOT NULL,
    evidence_ranks_json jsonb,
    channels_json jsonb NOT NULL,
    CONSTRAINT eval_run_items_pkey PRIMARY KEY (id),
    CONSTRAINT uq_eval_run_items_run_item UNIQUE (run_id, testset_item_id),
    CONSTRAINT eval_run_items_run_id_fkey
        FOREIGN KEY (run_id) REFERENCES eval_runs(id) ON DELETE CASCADE,
    CONSTRAINT eval_run_items_testset_item_id_fkey
        FOREIGN KEY (testset_item_id) REFERENCES eval_testset_items(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_eval_run_items_testset_item_id ON eval_run_items USING btree (testset_item_id);

CREATE TABLE IF NOT EXISTS eval_run_tasks (
    id character varying(36) NOT NULL,
    run_id character varying(36) NOT NULL,
    item_id character varying(36) NOT NULL,
    status character varying(16) DEFAULT 'pending' NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    last_error text,
    next_retry_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    queued_at timestamp with time zone,
    CONSTRAINT eval_run_tasks_pkey PRIMARY KEY (id),
    CONSTRAINT uq_eval_run_tasks_run_item UNIQUE (run_id, item_id),
    CONSTRAINT eval_run_tasks_run_id_fkey
        FOREIGN KEY (run_id) REFERENCES eval_runs(id) ON DELETE CASCADE,
    CONSTRAINT eval_run_tasks_item_id_fkey
        FOREIGN KEY (item_id) REFERENCES eval_testset_items(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_eval_run_tasks_run_id ON eval_run_tasks USING btree (run_id);

CREATE INDEX IF NOT EXISTS ix_eval_run_tasks_status_next_retry ON eval_run_tasks USING btree (status, next_retry_at);

COMMIT;
