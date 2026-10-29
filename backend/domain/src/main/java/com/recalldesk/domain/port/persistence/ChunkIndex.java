package com.recalldesk.domain.port.persistence;

import com.recalldesk.domain.retrieval.ChunkHit;
import com.recalldesk.domain.retrieval.ChunkRecord;
import java.util.List;
import java.util.Optional;

/**
 * chunk 级存储与单路检索原语（dense / sparse 各一路），由 PostgreSQL 实现。
 *
 * 这里只放单条语句级别的原语：「整篇替换 = 先删后插」这类编排归应用服务（IndexingService），
 * 由它用 UnitOfWork 把两条原语框成一个事务，适配器自己不提交事务。
 *
 * chunks 表里的 text 是可丢弃的派生副本——真权威是磁盘原始文件 + 重索引链路，索引表整个
 * 删掉都不心疼，reindex 一键重灌。BM25 全文索引物理上要求文本住在引擎里，所以 text 存在
 * 列上，供 searchBySparse / getChunk / getDocumentChunks 直接返回。
 *
 * 两路检索都吃 userId：归属是**索引内的过滤条件**，不是取回后的应用层筛。这不是优化而是
 * 正确性——过滤若落在 TopK 之后，用户实际拿到的条数会少于 limit，看起来像「召回变差了」。
 * 因此写入块时必须把归属一起写进去（那份 user_id 由 documents 行抄来，只在 reindex 时写）。
 *
 * 融合（RRF）、改写、重排等编排不属于本端口，归 SearchService。
 */
public interface ChunkIndex {

    /** 批量写入一个文档的块；旧块由调用方在同一工作单元里先删（见 {@link #deleteDocument}）。 */
    void insertChunks(
            String documentId, String userId, String documentName, List<String> chunks, List<double[]> vectors);

    /** 稠密向量检索（语义路），score 为余弦相似度，0~1；只在给定用户的块里找。 */
    List<ChunkHit> searchByDense(double[] denseVector, int topK, String userId);

    /** 关键词检索（BM25 路），score 为 BM25 分数，无界；只在给定用户的块里找。 */
    List<ChunkHit> searchBySparse(String queryText, int topK, String userId);

    /** 取回一个文档的全部分块，按 chunkIndex 升序（授权由调用方在 documents 上完成）。 */
    List<ChunkRecord> getDocumentChunks(String documentId);

    /** 按坐标精确取一个分块；块不存在返回空。 */
    Optional<ChunkRecord> getChunk(String documentId, int chunkIndex);

    /** 删除一个文档的全部块（没有就是空操作，幂等）。 */
    void deleteDocument(String documentId);
}
