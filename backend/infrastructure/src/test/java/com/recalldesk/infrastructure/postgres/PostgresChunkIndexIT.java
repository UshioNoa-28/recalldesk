package com.recalldesk.infrastructure.postgres;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.recalldesk.domain.retrieval.ChunkHit;
import com.recalldesk.domain.retrieval.ChunkRecord;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

/**
 * 真库对拍（不灌进默认 test 运行，靠 {@code -Dtest=PostgresChunkIndexIT} 手动拉起）：
 * 同一个 ParadeDB、同一批查询，Java adapter 的结果落 JSON，再和参考快照比。
 * 读对拍在前，写路径自检在后并清干净——写会动 BM25 的文档频次，混在一起分数就不可比了。
 */
class PostgresChunkIndexIT {

    private static final String JDBC_URL = "jdbc:postgresql://127.0.0.1:5435/anna_rag";
    private static final String TEMP_DOC = "java-it-temp-doc";
    private static final String TEMP_USER = "java-it-user";
    private static final List<String> QUERIES = List.of("insurance", "the", "报销 住宿", "openai model training");

    @Test
    void dumpResultsForParityDiff() throws Exception {
        JdbcTemplate jdbc = new JdbcTemplate(
                org.springframework.jdbc.datasource.SingleConnectionDataSource.class
                        .getConstructor(String.class, String.class, String.class, boolean.class)
                        .newInstance(JDBC_URL, "rag", "rag", true));
        PostgresChunkIndex index = new PostgresChunkIndex(jdbc);

        // 归属谓词是新加的，对拍时得挑语料自己的 user：库里这批块全属同一个人，
        // 加了过滤的结果与参考快照才可比（库里换过多用户语料时这个前提就不成立了）
        String corpusUser = jdbc.queryForObject(
                "SELECT user_id FROM chunks WHERE embedding IS NOT NULL ORDER BY doc_id, chunk_index LIMIT 1",
                String.class);
        ObjectNode out = new ObjectMapper().createObjectNode();
        out.put("user_id", corpusUser);
        ArrayNode queries = out.putArray("sparse");
        for (String q : QUERIES) {
            ArrayNode hits = queries.addObject().put("query", q).putArray("hits");
            for (ChunkHit hit : index.searchBySparse(q, 10, corpusUser)) {
                hits.addObject()
                        .put("document_id", hit.documentId())
                        .put("chunk_index", hit.chunkIndex())
                        .put("score", hit.score());
            }
        }

        double[] seedVector = firstEmbedding(jdbc);
        ArrayNode dense = out.putArray("dense");
        for (int topK : List.of(5, 20)) {
            ArrayNode hits = dense.addObject().put("top_k", topK).putArray("hits");
            for (ChunkHit hit : index.searchByDense(seedVector, topK, corpusUser)) {
                hits.addObject()
                        .put("document_id", hit.documentId())
                        .put("chunk_index", hit.chunkIndex())
                        .put("score", hit.score());
            }
        }

        writePathSelfCheck(index, jdbc, out.putObject("write"));
        java.nio.file.Files.writeString(
                java.nio.file.Path.of("/tmp/java_chunk_index.json"), new ObjectMapper().writeValueAsString(out));
    }

    /** 取一条真实向量的字面量当查询向量：两侧解析同一串文本，才排掉随机扰动。 */
    private static double[] firstEmbedding(JdbcTemplate jdbc) {
        String literal = jdbc.queryForObject(
                "SELECT embedding::text FROM chunks WHERE embedding IS NOT NULL ORDER BY doc_id, chunk_index LIMIT 1",
                String.class);
        String[] parts = literal.substring(1, literal.length() - 1).split(",");
        double[] vector = new double[parts.length];
        for (int i = 0; i < parts.length; i++) {
            vector[i] = Double.parseDouble(parts[i].trim());
        }
        return vector;
    }

    /** 先删后插（整篇替换）→ 回读 → 精确取块 → 删；只碰临时 doc_id，跑完自己扫干净。 */
    private static void writePathSelfCheck(PostgresChunkIndex index, JdbcTemplate jdbc, ObjectNode report) {
        // chunks.doc_id 现在有外键：临时块必须挂在一个真实的 documents 行下
        jdbc.update("INSERT INTO users (id, username, password_hash, created_at) "
                + "VALUES (?, ?, 'java-it', now()) ON CONFLICT (id) DO NOTHING", TEMP_USER, TEMP_USER);
        jdbc.update("INSERT INTO documents (id, user_id, name, storage_key, size_bytes, status, created_at) "
                + "VALUES (?, ?, 'java-it.doc', 'java-it', 0, 'success', now()) ON CONFLICT (id) DO NOTHING",
                TEMP_DOC, TEMP_USER);
        try {
            double[] zero = new double[1024];
            double[] unit = new double[1024];
            unit[0] = 1.0;
            index.insertChunks(
                    TEMP_DOC, TEMP_USER, "java-it.doc", List.of("校准临时块 甲", "校准临时块 乙"), List.of(unit, zero));
            report.put("written", index.getDocumentChunks(TEMP_DOC).size());
            index.deleteDocument(TEMP_DOC);
            index.insertChunks(TEMP_DOC, TEMP_USER, "java-it.doc", List.of("校准临时块 甲"), List.of(unit));
            report.put("replaced_twice", index.getDocumentChunks(TEMP_DOC).size());
            List<ChunkRecord> all = index.getDocumentChunks(TEMP_DOC);
            report.put("document_chunks", all.size());
            report.put("get_chunk_text", all.isEmpty() ? null : index.getChunk(TEMP_DOC, 0).map(ChunkRecord::text).orElse(null));
            report.put("get_missing_chunk", index.getChunk(TEMP_DOC, 99).isPresent());
            report.put("sparse_sees_new_row", !index.searchBySparse("校准临时块", 5, TEMP_USER).isEmpty());
            // 归属过滤真的在 SQL 里生效：同一批块、同一个查询，换个 user 就什么都捞不到
            report.put("sparse_hides_other_user", index.searchBySparse("校准临时块", 5, "另一个用户").isEmpty());
            report.put("dense_hides_other_user", index.searchByDense(unit, 10, "另一个用户").isEmpty());
        } finally {
            index.deleteDocument(TEMP_DOC);
            jdbc.update("DELETE FROM documents WHERE id = ?", TEMP_DOC);
            jdbc.update("DELETE FROM users WHERE id = ?", TEMP_USER);
            report.put("cleanup_rows", countTempRows());
        }
    }

    private static int countTempRows() {
        try (Connection conn = DriverManager.getConnection(JDBC_URL, "rag", "rag");
                Statement st = conn.createStatement();
                ResultSet rs = st.executeQuery(
                        "SELECT count(*) FROM chunks WHERE doc_id = '" + TEMP_DOC + "'")) {
            return rs.next() ? rs.getInt(1) : -1;
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
