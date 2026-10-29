package com.recalldesk.application.eval;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.recalldesk.application.FakeTransactionManager;
import com.recalldesk.domain.Page;
import com.recalldesk.domain.documents.Document;
import com.recalldesk.domain.documents.DocumentStatus;
import com.recalldesk.domain.eval.EvalTestSet;
import com.recalldesk.application.eval.dto.EvalTestSetDetail;
import com.recalldesk.domain.eval.EvalTestSetItem;
import com.recalldesk.domain.eval.EvidenceQuote;
import com.recalldesk.application.eval.dto.ImportedQuestion;
import com.recalldesk.application.eval.dto.ImportedQuestion.ImportedChunk;
import com.recalldesk.domain.exception.eval.TestSetNotFoundException;
import com.recalldesk.domain.port.persistence.ChunkIndex;
import com.recalldesk.domain.port.persistence.DocumentRepository;
import com.recalldesk.domain.port.persistence.EvalRepository;
import com.recalldesk.domain.retrieval.ChunkHit;
import com.recalldesk.domain.retrieval.ChunkRecord;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * EvalService 用例测试（全 fake，不连 PG）：建集、导入题目、归属隔离、整批拒绝。
 *
 * 导入是同步的，所以这里断言的重心从「有没有派出任务」变成了「有没有落下半成品」：
 * 一次被拒的上传必须在库里什么都不留，否则评测集的分母就没人说得清了。
 */
class EvalServiceTest {

    private static final Instant CREATED_AT = Instant.parse("2026-09-03T12:00:00Z");
    private static final String ALICE = "user-alice";
    private static final String BOB = "user-bob";

    /** 一篇三个块的小文档，文本够长以保证引文能精确命中。 */
    private static final String CHUNK_0 = "出箱投递的核心是业务事务只写 document_tasks 表。";
    private static final String CHUNK_1 = "publisher 用 FOR UPDATE SKIP LOCKED 轮询出箱。";
    private static final String CHUNK_2 = "consumer 在数据库提交之后才 ACK 队列消息。";

    private static Document document(String id, String userId, String name) {
        return new Document(id, userId, name, id + ".txt", 10, "text/plain",
                DocumentStatus.SUCCESS, null, null, CREATED_AT, null);
    }

    private static ChunkRecord record(String documentId, int chunkIndex, String text) {
        return new ChunkRecord(documentId, chunkIndex, text, documentId + ".txt", 3);
    }

    private static ImportedQuestion question(String query, ImportedChunk... chunks) {
        return new ImportedQuestion(query, List.of(chunks));
    }

    private static ImportedChunk gold(String documentId, int chunkIndex) {
        return new ImportedChunk(documentId, chunkIndex);
    }

    /** 内存评测集：按用户归属，题目连着引文一起存，形状与真仓储同构。 */
    private static class FakeEvalRepository implements EvalRepository {

        final Map<String, EvalTestSet> testSets = new LinkedHashMap<>();
        final Map<String, List<EvalTestSetItem>> items = new LinkedHashMap<>();
        final List<List<String>> evidenceUpdates = new ArrayList<>();

        @Override
        public void createTestSet(String testSetId, String userId, String name) {
            testSets.put(testSetId, new EvalTestSet(testSetId, userId, name, 0, CREATED_AT));
            items.put(testSetId, new ArrayList<>());
        }

        @Override
        public Optional<EvalTestSet> getTestSet(String userId, String testSetId) {
            EvalTestSet testSet = testSets.get(testSetId);
            if (testSet == null || !testSet.userId().equals(userId)) {
                return Optional.empty();
            }
            EvalTestSet withCount = new EvalTestSet(testSet.id(), testSet.userId(), testSet.name(),
                    items.getOrDefault(testSetId, List.of()).size(), testSet.createdAt());
            testSets.put(testSetId, withCount);
            return Optional.of(withCount);
        }

        @Override
        public List<EvalTestSet> listTestSets(String userId) {
            List<EvalTestSet> all = new ArrayList<>();
            testSets.keySet().forEach(id -> getTestSet(userId, id).ifPresent(all::add));
            return all;
        }

        @Override
        public void deleteTestSet(String userId, String testSetId) {
            getTestSet(userId, testSetId).ifPresent(testSet -> {
                testSets.remove(testSetId);
                items.remove(testSetId);
            });
        }

        @Override
        public void addItems(String testSetId, List<EvalTestSetItem> newItems) {
            items.computeIfAbsent(testSetId, id -> new ArrayList<>()).addAll(newItems);
        }

        @Override
        public List<EvalTestSetItem> listTestSetItems(String testSetId) {
            return List.copyOf(items.getOrDefault(testSetId, List.of()));
        }

        @Override
        public Optional<EvalTestSetItem> getItem(String itemId) {
            return items.values().stream().flatMap(List::stream).filter(item -> item.id().equals(itemId)).findFirst();
        }

        @Override
        public int deleteItemsReferencingDocument(String documentId) {
            int removed = 0;
            for (List<EvalTestSetItem> stored : items.values()) {
                removed += (int) stored.stream()
                        .filter(item -> item.evidence().stream().anyMatch(
                                evidence -> evidence.documentId().equals(documentId)))
                        .count();
                stored.removeIf(item -> item.evidence().stream().anyMatch(
                        evidence -> evidence.documentId().equals(documentId)));
            }
            return removed;
        }
    }

    private static class FakeDocumentRepository implements DocumentRepository {

        final Map<String, Document> documents;

        FakeDocumentRepository(Map<String, Document> documents) {
            this.documents = documents;
        }

        @Override
        public Optional<Document> get(String documentId) {
            return Optional.ofNullable(documents.get(documentId));
        }

        @Override
        public Optional<Document> getOwned(String userId, String documentId) {
            return get(documentId).filter(doc -> doc.userId().equals(userId));
        }

        @Override
        public void add(Document document) {}

        @Override
        public Page<Document> list(String userId, int page, int pageSize) {
            return new Page<>(List.copyOf(documents.values()), documents.size());
        }

        @Override
        public void update(Document document) {}

        @Override
        public boolean delete(String userId, String documentId) {
            return documents.remove(documentId) != null;
        }
    }

    /** 只回读分块文本：解析引文用的就是这条路径，检索那几路在本用例里不该被走到。 */
    private static class FakeChunkIndex implements ChunkIndex {

        final Map<String, List<ChunkRecord>> records;
        final List<String> scrolled = new ArrayList<>();

        FakeChunkIndex(Map<String, List<ChunkRecord>> records) {
            this.records = records;
        }

        @Override
        public List<ChunkRecord> getDocumentChunks(String documentId) {
            scrolled.add(documentId);
            return records.getOrDefault(documentId, List.of());
        }

        @Override
        public void insertChunks(
                String documentId, String userId, String documentName, List<String> chunks, List<double[]> vectors) {
            throw new UnsupportedOperationException();
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
        public Optional<ChunkRecord> getChunk(String documentId, int chunkIndex) {
            return getDocumentChunks(documentId).stream()
                    .filter(chunk -> chunk.chunkIndex() == chunkIndex)
                    .findFirst();
        }

        @Override
        public void deleteDocument(String documentId) {}
    }

    /** 共享装配：一份「Alice 的一篇文档 + 三个块」的默认世界。 */
    private static class Harness {

        final FakeEvalRepository evals = new FakeEvalRepository();
        final FakeDocumentRepository documents;
        final FakeChunkIndex index;
        final FakeTransactionManager txManager = new FakeTransactionManager();
        final EvalService service;

        Harness() {
            this(Map.of("doc-1", document("doc-1", ALICE, "营养指南.txt")),
                    Map.of("doc-1", List.of(
                            record("doc-1", 0, CHUNK_0),
                            record("doc-1", 1, CHUNK_1),
                            record("doc-1", 2, CHUNK_2))));
        }

        Harness(Map<String, Document> documents, Map<String, List<ChunkRecord>> chunks) {
            this.documents = new FakeDocumentRepository(documents);
            this.index = new FakeChunkIndex(chunks);
            this.service = new EvalService(evals, this.documents, index, txManager.unitOfWork());
        }

        int commits() {
            return txManager.commits;
        }

        String create(String name) {
            return service.createTestSet(ALICE, name).testSet().id();
        }

        List<EvalTestSetItem> stored(String testSetId) {
            return evals.listTestSetItems(testSetId);
        }
    }

    @Test
    @DisplayName("建集：一个事务写一行空集，归到调用方名下")
    void createTestSetWritesOneOwnedRow() {
        Harness harness = new Harness();

        EvalTestSetDetail result = harness.service.createTestSet(ALICE, "水果题集");

        assertThat(harness.commits()).isEqualTo(1);
        assertThat(result.testSet().userId()).isEqualTo(ALICE);
        assertThat(result.testSet().name()).isEqualTo("水果题集");
        assertThat(result.testSet().itemCount()).isZero();
        assertThat(result.items()).isEmpty();
    }

    @Test
    @DisplayName("空名字回落默认名，前后空白削掉")
    void blankNameFallsBackToDefault() {
        Harness harness = new Harness();

        assertThat(harness.service.createTestSet(ALICE, "   ").testSet().name())
                .isEqualTo(EvalService.DEFAULT_TESTSET_NAME);
        assertThat(harness.service.createTestSet(ALICE, "  题集  ").testSet().name()).isEqualTo("题集");
    }

    @Test
    @DisplayName("导入：引文解析成落点后一次事务落库，题目进来就是终态")
    void importItemsResolvesQuotesAndWritesOnce() {
        Harness harness = new Harness();
        String testSetId = harness.create("水果题集");

        EvalTestSetDetail result = harness.service.importItems(ALICE, testSetId, List.of(
                question("出箱怎么解耦？", gold("doc-1", 0)),
                question("谁负责认领孤儿？", gold("doc-1", 2))));

        assertThat(harness.commits()).isEqualTo(2); // 建集一次、导入一次
        assertThat(result.testSet().itemCount()).isEqualTo(2);
        assertThat(result.items()).hasSize(2);
        EvidenceQuote first = result.items().getFirst().evidence().getFirst();
        assertThat(first.documentId()).isEqualTo("doc-1");
        assertThat(first.chunkIndex()).isZero();
        assertThat(result.items().get(1).evidence().getFirst().chunkIndex()).isEqualTo(2);
    }

    @Test
    @DisplayName("金标块越界：整批拒绝，并指出是第几块、文档共几块")
    void chunkIndexOutOfRangeRejectsTheWholeUpload() {
        Harness harness = new Harness();
        String testSetId = harness.create("越界");

        assertThatThrownBy(() -> harness.service.importItems(ALICE, testSetId, List.of(
                        question("越界", gold("doc-1", 3)))))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("超出文档")
                .hasMessageContaining("共 3 块");

        assertThat(harness.stored(testSetId)).isEmpty();
    }

    @Test
    @DisplayName("一篇文档的分块只回读一次：多段引文不重复扫索引")
    void chunksAreScrolledOncePerDocument() {
        Harness harness = new Harness();
        String testSetId = harness.create("滚动");

        harness.service.importItems(ALICE, testSetId, List.of(
                question("一", gold("doc-1", 0)),
                question("二", gold("doc-1", 2))));

        assertThat(harness.index.scrolled).containsExactly("doc-1");
    }

    @Test
    @DisplayName("多个金标一题：ordinal 按给出顺序，块号原样落库")
    void multipleGoldChunksInOneItem() {
        Harness harness = new Harness();
        String testSetId = harness.create("多跳");

        EvalTestSetDetail result = harness.service.importItems(ALICE, testSetId, List.of(
                question("串起来", gold("doc-1", 0), gold("doc-1", 2))));

        List<EvidenceQuote> evidence = result.items().getFirst().evidence();
        assertThat(evidence).hasSize(2);
        assertThat(evidence).extracting(EvidenceQuote::ordinal).containsExactly(0, 1);
        assertThat(evidence).extracting(EvidenceQuote::chunkIndex).containsExactly(0, 2);
    }

    @Test
    @DisplayName("文档没有索引块：整批拒绝、一个字都不写，并把是哪道题报回去")
    void documentWithoutChunksRejectsTheWholeUpload() {
        Harness harness = new Harness(
                Map.of("doc-1", document("doc-1", ALICE, "营养指南.txt")), Map.of("doc-1", List.of()));
        String testSetId = harness.create("x");
        int commitsBefore = harness.commits();

        assertThatThrownBy(() -> harness.service.importItems(ALICE, testSetId, List.of(
                        question("好的", gold("doc-1", 0)),
                        question("坏的", gold("doc-1", 1)))))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("还没有索引块")
                .hasMessageContaining("坏的");

        assertThat(harness.commits()).isEqualTo(commitsBefore);
        assertThat(harness.stored(testSetId)).isEmpty();
    }

    @Test
    @DisplayName("文档不是调用方的：与不存在同一个说法，且不泄漏对方的存在")
    void foreignDocumentIsReportedAsMissing() {
        Harness harness = new Harness(
                Map.of("doc-2", document("doc-2", BOB, "别人的.txt")),
                Map.of("doc-2", List.of(record("doc-2", 0, CHUNK_0))));
        String testSetId = harness.create("x");

        assertThatThrownBy(() -> harness.service.importItems(ALICE, testSetId, List.of(
                question("q", gold("doc-2", 0)))))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("不存在（或不属于你）");

        assertThat(harness.stored(testSetId)).isEmpty();
    }

    @Test
    @DisplayName("文档还没索引块：说清是等索引，而不是引文写错")
    void documentWithoutChunksIsRejectedWithItsOwnReason() {
        Harness harness = new Harness(
                Map.of("doc-3", document("doc-3", ALICE, "空的.txt")), Map.of());
        String testSetId = harness.create("x");

        assertThatThrownBy(() -> harness.service.importItems(ALICE, testSetId, List.of(
                question("q", gold("doc-3", 0)))))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("还没有索引块");
    }

    @Test
    @DisplayName("一题超过五个金标：拒绝并报出上限")
    void tooManyGoldChunksInOneItem() {
        Harness harness = new Harness();
        String testSetId = harness.create("x");
        List<ImportedChunk> six = new ArrayList<>();
        for (int i = 0; i < 6; i++) {
            six.add(gold("doc-1", 0));
        }

        assertThatThrownBy(() -> harness.service.importItems(
                ALICE, testSetId, List.of(new ImportedQuestion("q", six))))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("超过上限");

        assertThat(harness.stored(testSetId)).isEmpty();
    }

    @Test
    @DisplayName("一次上传题数封顶：解析要在请求内读完整篇文档，别拿它当批处理入口")
    void uploadSizeIsCapped() {
        Harness harness = new Harness();
        String testSetId = harness.create("x");
        List<ImportedQuestion> questions = new ArrayList<>();
        for (int i = 0; i <= EvalService.MAX_ITEMS_PER_UPLOAD; i++) {
            questions.add(question("q" + i, gold("doc-1", 0)));
        }

        assertThatThrownBy(() -> harness.service.importItems(ALICE, testSetId, questions))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("一次最多导入");
    }

    @Test
    @DisplayName("空清单：不改动静，也不提交")
    void emptyUploadWritesNothing() {
        Harness harness = new Harness();
        String testSetId = harness.service.importItems(ALICE, harness.create("x"), List.of()).testSet().id();
        int commitsBefore = harness.commits();

        EvalTestSetDetail result = harness.service.importItems(ALICE, testSetId, List.of());

        assertThat(harness.commits()).isEqualTo(commitsBefore);
        assertThat(result.items()).isEmpty();
    }

    @Test
    @DisplayName("导入到不存在的集：404 语义，不提交任何东西")
    void unknownTestSetRaisesWithoutCommitting() {
        Harness harness = new Harness();

        assertThatThrownBy(() -> harness.service.importItems(
                ALICE, "ghost", List.of(question("q", gold("doc-1", 0)))))
                .isInstanceOf(TestSetNotFoundException.class);

        assertThat(harness.commits()).isZero();
    }

    @Test
    @DisplayName("别人的集等于不存在的集：列表、详情、删除都只看调用方自己的")
    void testSetsAreIsolatedPerUser() {
        Harness harness = new Harness();
        String testSetId = harness.create("水果题集");

        assertThat(harness.service.listTestSets(BOB)).isEmpty();
        assertThat(harness.service.listTestSets(ALICE)).hasSize(1);
        assertThatThrownBy(() -> harness.service.getTestSet(BOB, testSetId))
                .isInstanceOf(TestSetNotFoundException.class);
        assertThatThrownBy(() -> harness.service.deleteTestSet(BOB, testSetId))
                .isInstanceOf(TestSetNotFoundException.class);
        assertThat(harness.evals.testSets).containsKey(testSetId);

        harness.service.deleteTestSet(ALICE, testSetId);
        assertThat(harness.evals.testSets).isEmpty();
    }

    @Test
    @DisplayName("删文档连带清题：引用它的题数被报出来（用例在 DocumentService，这里钉端口行为）")
    void deleteItemsReferencingDocumentCountsRemovedItems() {
        Harness harness = new Harness();
        String testSetId = harness.create("水果题集");
        harness.service.importItems(ALICE, testSetId, List.of(
                question("一", gold("doc-1", 0)),
                question("二", gold("doc-1", 2))));

        assertThat(harness.evals.deleteItemsReferencingDocument("doc-1")).isEqualTo(2);
        assertThat(harness.stored(testSetId)).isEmpty();
    }
}
