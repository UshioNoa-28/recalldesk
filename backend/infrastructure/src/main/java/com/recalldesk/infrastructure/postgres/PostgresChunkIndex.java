package com.recalldesk.infrastructure.postgres;

import com.recalldesk.domain.port.persistence.ChunkIndex;
import com.recalldesk.domain.retrieval.ChunkHit;
import com.recalldesk.domain.retrieval.ChunkRecord;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * chunk 检索索引的 PostgreSQL 实现：dense 走 pgvector 的 HNSW（cosine），sparse 走 pg_search 的
 * BM25 全文索引，两路都在 chunks 这一张表上。
 *
 * 这里只执行单条 SQL，不开事务：「整篇替换 = 先删后插」由 IndexingService 用 UnitOfWork 编排，
 * 两条语句在同一个工作单元里，插入失败时旧块还在，不会留下「文档行还在、索引块没了」的半写状态。
 */
@Repository
public class PostgresChunkIndex implements ChunkIndex {

    private static final String HIT_COLUMNS = "doc_id, document_name, chunk_index, chunk_count, text";

    private final JdbcTemplate jdbc;

    public PostgresChunkIndex(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public void insertChunks(
            String documentId,
            String userId,
            String documentName,
            List<String> chunks,
            List<double[]> vectors) {
        if (chunks.size() != vectors.size()) {
            throw new IllegalArgumentException(
                    "chunks 与 vectors 数量不符：" + chunks.size() + " vs " + vectors.size());
        }
        List<Object[]> batch = new ArrayList<>(chunks.size());
        for (int i = 0; i < chunks.size(); i++) {
            batch.add(new Object[] {
                documentId, userId, i, documentName, chunks.size(), chunks.get(i), vectorLiteral(vectors.get(i))
            });
        }
        jdbc.batchUpdate(
                "INSERT INTO chunks (doc_id, user_id, chunk_index, document_name, chunk_count, text, embedding) "
                        + "VALUES (?, ?, ?, ?, ?, ?, CAST(? AS vector))",
                batch);
    }

    @Override
    public List<ChunkHit> searchByDense(double[] denseVector, int topK, String userId) {
        if (denseVector == null || denseVector.length == 0) {
            return List.of();
        }
        // score 换成 1 - 距离，对齐"余弦相似度越大越好"
        String literal = vectorLiteral(denseVector);
        // user_id 谓词进 WHERE：HNSW 是「按距离取满 limit 再过滤」的扫描，带过滤时靠连接上
        // 设好的 hnsw.iterative_scan=relaxed_order 继续往后扫，否则这里会少给结果（见 schema 注释）
        return jdbc.query(
                "SELECT " + HIT_COLUMNS + ", 1 - (embedding <=> CAST(? AS vector)) AS score "
                        + "FROM chunks WHERE embedding IS NOT NULL AND user_id = ? "
                        + "ORDER BY embedding <=> CAST(? AS vector) LIMIT ?",
                this::mapHit,
                literal, userId, literal, topK);
    }

    @Override
    public List<ChunkHit> searchBySparse(String queryText, int topK, String userId) {
        String bm25 = Bm25Query.build(queryText);
        if (bm25.isEmpty()) {
            return List.of();
        }
        // score 取 paradedb.score(id) 原值，不在 SQL 里 round/cast——带 cast 的 ORDER BY
        // 表达式没法下推进索引，Top-K 扫描会退化成普通扫描
        // user_id 已在 bm25 索引里（raw 分词），于是它是扫描内的 always_filter 而不是扫后筛
        return jdbc.query(
                "SELECT " + HIT_COLUMNS + ", paradedb.score(id) AS score "
                        + "FROM chunks WHERE text @@@ CAST(? AS text) AND user_id = ? "
                        + "ORDER BY score DESC LIMIT ?",
                this::mapHit,
                bm25, userId, topK);
    }

    @Override
    public List<ChunkRecord> getDocumentChunks(String documentId) {
        return jdbc.query(
                "SELECT chunk_index, text, document_name, chunk_count FROM chunks "
                        + "WHERE doc_id = ? ORDER BY chunk_index",
                (rs, rowNum) -> record(documentId, rs),
                documentId);
    }

    @Override
    public Optional<ChunkRecord> getChunk(String documentId, int chunkIndex) {
        // 查询键本身即坐标，不必把它选回结果集
        return jdbc.query(
                        "SELECT text, document_name, chunk_count FROM chunks "
                                + "WHERE doc_id = ? AND chunk_index = ?",
                        (rs, rowNum) ->
                                new ChunkRecord(
                                        documentId,
                                        chunkIndex,
                                        rs.getString("text"),
                                        rs.getString("document_name"),
                                        chunkCount(rs)),
                        documentId,
                        chunkIndex)
                .stream()
                .findFirst();
    }

    @Override
    public void deleteDocument(String documentId) {
        jdbc.update("DELETE FROM chunks WHERE doc_id = ?", documentId);
    }

    private ChunkHit mapHit(ResultSet rs, int rowNum) throws SQLException {
        return new ChunkHit(
                rs.getString("doc_id"),
                rs.getString("document_name"),
                rs.getInt("chunk_index"),
                chunkCount(rs),
                rs.getString("text"),
                rs.getDouble("score"));
    }

    private static ChunkRecord record(String documentId, ResultSet rs) throws SQLException {
        return new ChunkRecord(
                documentId,
                rs.getInt("chunk_index"),
                rs.getString("text"),
                rs.getString("document_name"),
                chunkCount(rs));
    }

    private static Integer chunkCount(ResultSet rs) throws SQLException {
        int value = rs.getInt("chunk_count");
        return rs.wasNull() ? null : value;
    }

    private static String vectorLiteral(double[] vector) {
        StringBuilder text = new StringBuilder("[");
        for (int i = 0; i < vector.length; i++) {
            text.append(i == 0 ? "" : ",").append(vector[i]);
        }
        return text.append(']').toString();
    }
}
