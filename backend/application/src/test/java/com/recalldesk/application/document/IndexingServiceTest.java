package com.recalldesk.application.document;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.recalldesk.application.FakeTransactionManager;
import com.recalldesk.domain.exception.indexing.EmptyContentException;
import com.recalldesk.domain.port.persistence.ChunkIndex;
import com.recalldesk.domain.port.model.EmbeddingClient;
import com.recalldesk.domain.port.model.TextSplitter;
import com.recalldesk.domain.retrieval.ChunkHit;
import com.recalldesk.domain.retrieval.ChunkRecord;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/** IndexingService 单元测试（假仓储 / 假 embedding / 假分块器，离线跑）。 */
class IndexingServiceTest {

    /** 记下收到的每一笔写：断言"以什么姿势打到端口"就靠它。 */
    private static class FakeChunkIndex implements ChunkIndex {

        final List<String> insertedDocumentIds = new ArrayList<>();
        final List<String> insertedUserIds = new ArrayList<>();
        final List<String> insertedDocumentNames = new ArrayList<>();
        final List<List<String>> insertedChunks = new ArrayList<>();
        final List<List<double[]>> insertedVectors = new ArrayList<>();
        final List<String> deleted = new ArrayList<>();

        @Override
        public void insertChunks(
                String documentId, String userId, String documentName, List<String> chunks, List<double[]> vectors) {
            insertedDocumentIds.add(documentId);
            insertedUserIds.add(userId);
            insertedDocumentNames.add(documentName);
            insertedChunks.add(chunks);
            insertedVectors.add(vectors);
        }

        @Override
        public void deleteDocument(String documentId) {
            deleted.add(documentId);
        }

        @Override
        public List<ChunkHit> searchByDense(double[] denseVector, int topK, String userId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public List<ChunkHit> searchBySparse(String queryText, int topK, String userId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public List<ChunkRecord> getDocumentChunks(String documentId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public Optional<ChunkRecord> getChunk(String documentId, int chunkIndex) {
            throw new UnsupportedOperationException();
        }
    }

    /** 假 embedding：向量按文本长度填充，结果可预测。 */
    private static class FakeEmbeddingClient implements EmbeddingClient {

        final List<List<String>> batches = new ArrayList<>();

        @Override
        public List<double[]> embed(List<String> texts) {
            batches.add(texts);
            return texts.stream().map(this::embedOne).toList();
        }

        @Override
        public double[] embedOne(String text) {
            double[] vector = new double[4];
            Arrays.fill(vector, text.length());
            return vector;
        }
    }

    /** 按中文句末标点切：离线、确定性，不依赖分块尺寸配置。 */
    private static class SentenceSplitter implements TextSplitter {

        @Override
        public List<String> split(String text) {
            List<String> parts = new ArrayList<>();
            for (String part : text.split("(?<=[。！？])\\s*", -1)) {
                if (!part.isBlank()) {
                    parts.add(part);
                }
            }
            return parts;
        }
    }

    @Test
    @DisplayName("切块 → 整批 embedding → 先删旧块再整篇写入（同一事务），归属随块进索引")
    void ingestSplitsEmbedsAndReplacesChunks() {
        FakeChunkIndex index = new FakeChunkIndex();
        FakeEmbeddingClient embedding = new FakeEmbeddingClient();
        FakeTransactionManager tx = new FakeTransactionManager();
        IndexingService service =
                new IndexingService(index, embedding, new SentenceSplitter(), tx.unitOfWork());

        int written = service.ingest(
                "doc-9", "user-alice", "水果.txt", "苹果发布新款手机，性能强劲。香蕉富含维生素钾。");

        assertThat(written).isEqualTo(2);
        // 先删后插：重索引读到的永远是这一版的块，而不是新旧混在一起
        assertThat(index.deleted).containsExactly("doc-9");
        assertThat(index.insertedDocumentIds).containsExactly("doc-9");
        // user_id 是检索侧的过滤条件，必须在这一笔写里落进块里，否则别人的查询筛不出它
        assertThat(index.insertedUserIds).containsExactly("user-alice");
        assertThat(index.insertedDocumentNames).containsExactly("水果.txt");
        assertThat(index.insertedChunks.getFirst()).hasSize(2);
        // 假 embedding 按文本长度填充：14 字 / 9 字
        assertThat(index.insertedVectors.getFirst()).extracting(vector -> vector[0]).containsExactly(14.0, 9.0);
        assertThat(embedding.batches.getFirst()).isEqualTo(index.insertedChunks.getFirst());
        assertThat(tx.commits).isEqualTo(1);
    }

    @Test
    @DisplayName("切不出块：内容问题响亮拒绝，不写「成功 0 块」的静默")
    void ingestEmptyDocumentRaises() {
        IndexingService service = new IndexingService(
                new FakeChunkIndex(), new FakeEmbeddingClient(), new SentenceSplitter(),
                new FakeTransactionManager().unitOfWork());

        assertThatThrownBy(() -> service.ingest("doc-9", "user-alice", "empty.txt", "   "))
                .isInstanceOf(EmptyContentException.class);
    }
}
