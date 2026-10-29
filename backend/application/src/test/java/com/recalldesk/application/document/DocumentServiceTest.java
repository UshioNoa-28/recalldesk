package com.recalldesk.application.document;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.recalldesk.domain.exception.indexing.EmptyContentException;
import com.recalldesk.application.FakeTransactionManager;
import com.recalldesk.application.document.dto.DocumentContent;
import com.recalldesk.application.search.dto.SearchOutcome;
import com.recalldesk.application.search.SearchService;
import com.recalldesk.domain.Page;
import com.recalldesk.domain.documents.Document;
import com.recalldesk.domain.exception.documents.DocumentNotFoundException;
import com.recalldesk.domain.documents.DocumentStatus;
import com.recalldesk.domain.documents.DocumentTask;
import com.recalldesk.domain.eval.EvalTestSet;
import com.recalldesk.domain.eval.EvalTestSetItem;
import com.recalldesk.domain.eval.EvalRun;
import com.recalldesk.domain.eval.EvalRunConfig;
import com.recalldesk.domain.eval.EvalRunItem;
import com.recalldesk.domain.eval.EvalRunStatus;
import com.recalldesk.domain.port.persistence.ChunkIndex;
import com.recalldesk.domain.port.persistence.DocumentFileStorage;
import com.recalldesk.domain.port.persistence.DocumentRepository;
import com.recalldesk.domain.port.persistence.DocumentTaskRepository;
import com.recalldesk.domain.port.persistence.EvalRepository;
import com.recalldesk.domain.port.persistence.EvalRunRepository;
import com.recalldesk.domain.port.model.TextSplitter;
import com.recalldesk.domain.retrieval.ChunkHit;
import com.recalldesk.domain.retrieval.ChunkRecord;
import com.recalldesk.application.search.dto.SearchProfile;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/** DocumentService 用例测试（全 fake，不依赖外部服务，事务用计数的假事务管理器）。 */
class DocumentServiceTest {

    private static final String ALICE = "user-alice";
    private static final String BOB = "user-bob";

    private static class FakeDocumentRepository implements DocumentRepository {

        final List<Document> added = new ArrayList<>();
        final List<String> deletedIds = new ArrayList<>();
        boolean failOnAdd;

        @Override
        public void add(Document document) {
            if (failOnAdd) {
                throw new IllegalStateException("db down");
            }
            added.add(document);
        }

        /** worker 路径：不看归属——它的授权来自 outbox，不是某个用户。 */
        @Override
        public Optional<Document> get(String documentId) {
            return added.stream().filter(doc -> doc.id().equals(documentId)).findFirst();
        }

        @Override
        public Optional<Document> getOwned(String userId, String documentId) {
            return added.stream()
                    .filter(doc -> doc.id().equals(documentId) && doc.userId().equals(userId))
                    .findFirst();
        }

        @Override
        public Page<Document> list(String userId, int page, int pageSize) {
            List<Document> owned = added.stream().filter(doc -> doc.userId().equals(userId)).toList();
            return new Page<>(owned, owned.size());
        }

        @Override
        public void update(Document document) {
            for (int i = 0; i < added.size(); i++) {
                if (added.get(i).id().equals(document.id())) {
                    added.set(i, document);
                    return;
                }
            }
            throw new java.util.NoSuchElementException(document.id());
        }

        @Override
        public boolean delete(String userId, String documentId) {
            boolean removed = added.removeIf(doc -> doc.id().equals(documentId) && doc.userId().equals(userId));
            if (removed) {
                deletedIds.add(documentId);
            }
            return removed;
        }
    }

    private static class FakeOutboxRepository implements DocumentTaskRepository {

        final List<String> added = new ArrayList<>();

        @Override
        public void add(String documentId) {
            added.add(documentId);
        }

        @Override
        public Optional<DocumentTask> get(String entryId) {
            return Optional.empty();
        }

        @Override
        public List<DocumentTask> listPending(int limit) {
            return List.of();
        }

        @Override
        public void markQueued(String entryId) {}

        @Override
        public void markSuccess(String entryId) {}

        @Override
        public void recordFailure(String entryId, String error) {}

        @Override
        public void markFailed(String entryId) {}
    }

    private static class FakeFileStorage implements DocumentFileStorage {

        final List<String> savedKeys = new ArrayList<>();
        final List<String> deleted = new ArrayList<>();
        final java.util.Map<String, byte[]> files = new java.util.LinkedHashMap<>();

        @Override
        public String save(String documentId, byte[] content) {
            String key = "uploads/" + documentId;
            savedKeys.add(key);
            files.put(key, content);
            return key;
        }

        @Override
        public byte[] read(String storageKey) {
            return files.get(storageKey);
        }

        @Override
        public void delete(String storageKey) {
            deleted.add(storageKey);
        }
    }

    private static class FakeChunkIndex implements ChunkIndex {

        final List<ChunkRecord> records;
        final List<String> deleted = new ArrayList<>();

        FakeChunkIndex(List<ChunkRecord> records) {
            this.records = records;
        }

        @Override
        public List<ChunkRecord> getDocumentChunks(String documentId) {
            return records;
        }

        @Override
        public void deleteDocument(String documentId) {
            deleted.add(documentId);
        }

        @Override
        public void insertChunks(
                String documentId, String userId, String documentName, List<String> chunks, List<double[]> vectors) {}

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
            throw new UnsupportedOperationException();
        }
    }

    /** 只用得上 delete_items_referencing_document：删文档时清证据题。 */
    private static class FakeEvalRepository implements EvalRepository {

        final List<String> purgedFor = new ArrayList<>();
        int removed;

        FakeEvalRepository(int removed) {
            this.removed = removed;
        }

        @Override
        public int deleteItemsReferencingDocument(String documentId) {
            purgedFor.add(documentId);
            return removed;
        }

        @Override
        public void createTestSet(String testSetId, String userId, String name) {
            throw new UnsupportedOperationException();
        }

        @Override
        public Optional<EvalTestSet> getTestSet(String userId, String testSetId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public List<EvalTestSet> listTestSets(String userId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public void deleteTestSet(String userId, String testSetId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public void addItems(String testSetId, List<EvalTestSetItem> items) {
            throw new UnsupportedOperationException();
        }

        @Override
        public List<EvalTestSetItem> listTestSetItems(String testSetId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public Optional<EvalTestSetItem> getItem(String itemId) {
            throw new UnsupportedOperationException();
        }

    }

    /** 只用得上 delete_runs_referencing_document：删文档时连 run 一起清。 */
    private static class FakeEvalRunRepository implements EvalRunRepository {

        final List<String> purgedFor = new ArrayList<>();

        @Override
        public int deleteRunsReferencingDocument(String documentId) {
            purgedFor.add(documentId);
            return 0;
        }

        @Override
        public void createRun(String runId, String userId, String testsetId, EvalRunConfig config) {
            throw new UnsupportedOperationException();
        }

        @Override
        public void recordRunItem(String runId, EvalRunItem result) {
            throw new UnsupportedOperationException();
        }

        @Override
        public void finishRun(
                String runId, EvalRunStatus status, Map<String, Object> metrics, String errorMessage) {
            throw new UnsupportedOperationException();
        }

        @Override
        public Optional<EvalRun> getRun(String runId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public Optional<EvalRun> getRunOwned(String userId, String runId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public List<EvalRunItem> listRunItems(String runId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public List<EvalRun> listRuns(String userId, String testsetId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public boolean hasRunResult(String runId, String testsetItemId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public void reopenRun(String runId) {
            throw new UnsupportedOperationException();
        }
    }

    /** 记下 profile 与 userId 怎么传下去的：/search 的开关与归属过滤必须原样落到 SearchService。 */
    private static class RecordingSearchService extends SearchService {

        SearchProfile lastProfile;
        Integer lastTopK;
        String lastUserId;
        final SearchOutcome outcome;

        RecordingSearchService(SearchOutcome outcome) {
            super(null, null, null, null, 10, 5, null);
            this.outcome = outcome;
        }

        @Override
        public SearchOutcome search(String query, Integer topK, SearchProfile profile, String userId) {
            lastTopK = topK;
            lastProfile = profile;
            lastUserId = userId;
            return outcome;
        }
    }

    /** 切得出块就行，具体尺寸不是本用例关心的：分块器自己有 golden 对拍。 */
    private static class NonBlankSplitter implements TextSplitter {

        @Override
        public List<String> split(String text) {
            return text.isBlank() ? List.of() : List.of(text.trim());
        }
    }

    private static class Harness {

        final FakeDocumentRepository repository = new FakeDocumentRepository();
        final FakeOutboxRepository outbox = new FakeOutboxRepository();
        final FakeFileStorage storage = new FakeFileStorage();
        FakeChunkIndex chunkIndex = new FakeChunkIndex(List.of());
        FakeEvalRepository evals = new FakeEvalRepository(0);
        final FakeEvalRunRepository evalRuns = new FakeEvalRunRepository();
        final FakeTransactionManager txManager = new FakeTransactionManager();
        RecordingSearchService search = new RecordingSearchService(new SearchOutcome(List.of(), List.of()));
        DocumentService service;

        Harness() {
            service = newService(new NonBlankSplitter());
        }

        DocumentService newService(TextSplitter splitter) {
            return new DocumentService(
                    repository,
                    storage,
                    outbox,
                    evals,
                    evalRuns,
                    chunkIndex,
                    splitter,
                    search,
                    txManager.unitOfWork());
        }

        int commits() {
            return txManager.commits;
        }

        /** 默认按 Alice 上传：本用例集绝大多数只关心一件事，userId 不重复写。 */
        Document ingestAsAlice(String name, String content) {
            return service.ingest(name, bytes(content), null, ALICE);
        }
    }

    private static byte[] bytes(String text) {
        return text.getBytes(StandardCharsets.UTF_8);
    }

    @Test
    @DisplayName("上传：文档 + 任务同事务提交，返回 PENDING，且不在请求内索引")
    void ingestWritesDocumentAndTaskThenCommits() {
        Harness harness = new Harness();

        Document document = harness.service.ingest("notes.txt", bytes("hello world"), "text/plain", ALICE);

        assertThat(document.status()).isEqualTo(DocumentStatus.PENDING);
        assertThat(harness.commits()).isEqualTo(1);
        assertThat(document.name()).isEqualTo("notes.txt");
        assertThat(document.userId()).isEqualTo(ALICE);
        assertThat(harness.storage.files.get("uploads/" + document.id())).isEqualTo(bytes("hello world"));
        assertThat(harness.outbox.added).containsExactly(document.id());
        // 上传阶段不碰检索链
        assertThat(harness.search.lastProfile).isNull();
    }

    @Test
    @DisplayName("数据库写失败：补偿删除已落盘的原件，事务没提交过")
    void ingestDeletesFileWhenDatabaseFails() {
        Harness harness = new Harness();
        harness.repository.failOnAdd = true;

        assertThatThrownBy(() -> harness.service.ingest("bad.txt", bytes("x"), null, ALICE))
                .isInstanceOf(IllegalStateException.class);

        assertThat(harness.storage.deleted).hasSize(1);
        assertThat(harness.commits()).isZero();
        assertThat(harness.outbox.added).isEmpty();
    }

    @Test
    @DisplayName("检索委托给 SearchService：top_k、档位与归属原样透传，不传 = 服务默认全开")
    void searchDelegatesToSearchService() {
        Harness harness = new Harness();
        ChunkHit hit = new ChunkHit("doc-1", "x", 0, 1, "hit", 1.0);
        harness.search = new RecordingSearchService(new SearchOutcome(List.of(hit), List.of()));
        DocumentService service = harness.newService(new NonBlankSplitter());

        List<ChunkHit> hits = service.search("query", 3, null, ALICE).hits();

        assertThat(hits).containsExactly(hit);
        assertThat(harness.search.lastTopK).isEqualTo(3);
        assertThat(harness.search.lastProfile).isNull();
        assertThat(harness.search.lastUserId).isEqualTo(ALICE);

        SearchProfile profile = new SearchProfile(false, false, null);
        service.search("query", 3, profile, BOB);
        assertThat(harness.search.lastProfile).isSameAs(profile);
        assertThat(harness.search.lastUserId).isEqualTo(BOB);
    }

    @Test
    @DisplayName("非 UTF-8 字节：当场拒，不落盘也不出任务")
    void ingestRejectsNonUtf8Content() {
        Harness harness = new Harness();

        assertThatThrownBy(() -> harness.service.ingest(
                "bad.txt", new byte[] {(byte) 0xff, (byte) 0xfe, 0}, null, ALICE))
                .isInstanceOf(IllegalArgumentException.class);

        assertThat(harness.storage.savedKeys).isEmpty();
        assertThat(harness.outbox.added).isEmpty();
    }

    @Test
    @DisplayName("全空白内容：读不出文本就是读不出，别派 worker 空跑退避")
    void ingestRejectsEmptyContent() {
        Harness harness = new Harness();

        assertThatThrownBy(() -> harness.service.ingest("empty.txt", bytes("   \n"), null, ALICE))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("内容为空");

        assertThat(harness.storage.savedKeys).isEmpty();
        assertThat(harness.outbox.added).isEmpty();
    }

    @Test
    @DisplayName("读得出文本但切不出块：同样是内容问题，入口拒")
    void ingestRejectsContentThatCannotBeSplit() {
        Harness harness = new Harness();
        DocumentService service = harness.newService(text -> List.of());

        assertThatThrownBy(() -> service.ingest("table.txt", bytes("id,name"), "text/plain", ALICE))
                .isInstanceOf(EmptyContentException.class)
                .hasMessageContaining("切不出");

        assertThat(harness.storage.savedKeys).isEmpty();
        assertThat(harness.outbox.added).isEmpty();
    }

    @Test
    @DisplayName("get 回读上传的那一行；不存在抛 DocumentNotFound（路由翻 404）")
    void getReturnsUploadedDocument() {
        Harness harness = new Harness();
        Document created = harness.ingestAsAlice("a.md", "hello");

        assertThat(harness.service.get(ALICE, created.id()).name()).isEqualTo("a.md");
        assertThatThrownBy(() -> harness.service.get(ALICE, "no-such-doc"))
                .isInstanceOf(DocumentNotFoundException.class);
    }

    @Test
    @DisplayName("越权读别人的文档：与不存在同一个答案，别让 id 空间变成可探测清单")
    void anotherUsersDocumentIsNotFound() {
        Harness harness = new Harness();
        Document created = harness.ingestAsAlice("a.md", "hello");

        assertThatThrownBy(() -> harness.service.get(BOB, created.id()))
                .isInstanceOf(DocumentNotFoundException.class);
        assertThatThrownBy(() -> harness.service.chunks(BOB, created.id()))
                .isInstanceOf(DocumentNotFoundException.class);
        assertThatThrownBy(() -> harness.service.reindex(BOB, created.id()))
                .isInstanceOf(DocumentNotFoundException.class);
        assertThat(harness.repository.deletedIds).isEmpty();
    }

    @Test
    @DisplayName("列表只看得到自己的；仓储分页原样透出")
    void listReturnsPageAsStored() {
        Harness harness = new Harness();
        harness.ingestAsAlice("a.md", "a");
        harness.ingestAsAlice("b.md", "b");
        harness.service.ingest("c.md", bytes("c"), null, BOB);

        Page<Document> result = harness.service.list(ALICE, 1, 10);

        assertThat(result.total()).isEqualTo(2);
        assertThat(result.items()).extracting(Document::name).containsExactly("a.md", "b.md");
        assertThat(result.items().getFirst().status()).isEqualTo(DocumentStatus.PENDING);
    }

    @Test
    @DisplayName("提交本身失败：文件补偿删除，异常照抛")
    void commitFailureDeletesFile() {
        Harness harness = new Harness();
        harness.txManager.failOnCommit = new IllegalStateException("commit failed");

        assertThatThrownBy(() -> harness.service.ingest("a.md", bytes("a"), null, ALICE))
                .isInstanceOf(IllegalStateException.class);

        assertThat(harness.storage.deleted).hasSize(1);
    }

    @Test
    @DisplayName("分块列表以索引库为准；文档不存在先 404，也不去碰索引")
    void chunksReturnsIndexRecords() {
        Harness harness = new Harness();
        FakeChunkIndex index = new FakeChunkIndex(List.of(
                new ChunkRecord("doc-1", 0, "第一段", "a.txt", 2),
                new ChunkRecord("doc-1", 1, "第二段", "a.txt", 2)));
        harness.chunkIndex = index;
        DocumentService service = harness.newService(new NonBlankSplitter());
        Document document = service.ingest("a.txt", bytes("第一段。第二段"), "text/plain", ALICE);

        List<ChunkRecord> records = service.chunks(ALICE, document.id());

        assertThat(records).extracting(ChunkRecord::text).containsExactly("第一段", "第二段");
        assertThatThrownBy(() -> service.chunks(ALICE, "missing")).isInstanceOf(DocumentNotFoundException.class);
    }

    @Test
    @DisplayName("原文回读：磁盘上的原件 + 重新抽取，不是 chunks 里的副本")
    void contentReturnsNameAndText() {
        Harness harness = new Harness();
        Document document = harness.ingestAsAlice("a.txt", "第一段。第二段");

        DocumentContent content = harness.service.content(ALICE, document.id());

        assertThat(content.name()).isEqualTo("a.txt");
        assertThat(content.text()).isEqualTo("第一段。第二段");
        assertThatThrownBy(() -> harness.service.content(BOB, document.id()))
                .isInstanceOf(DocumentNotFoundException.class);
    }

    @Test
    @DisplayName("删除：run + 引用题 + 文档行同事务，块与任务由外键级联，文件最后 best-effort")
    void deleteCascadesInOneTransaction() {
        Harness harness = new Harness();
        FakeChunkIndex index = new FakeChunkIndex(List.of());
        harness.chunkIndex = index;
        harness.evals = new FakeEvalRepository(2);
        DocumentService service = harness.newService(new NonBlankSplitter());
        Document document = service.ingest("a.txt", bytes("第一段。第二段"), "text/plain", ALICE);

        int removedItems = service.delete(ALICE, document.id());

        // 连带清掉几道题必须回给调用方：静默删掉别人攒好的评测集是最难查的数据丢失
        assertThat(removedItems).isEqualTo(2);
        assertThat(harness.evalRuns.purgedFor).containsExactly(document.id());
        assertThat(harness.evals.purgedFor).containsExactly(document.id());
        // 块由 chunks.doc_id 外键级联；任务随文档行级联：请求里不再排删除任务
        assertThat(index.deleted).isEmpty();
        assertThat(harness.outbox.added).containsExactly(document.id());
        assertThat(harness.repository.deletedIds).containsExactly(document.id());
        assertThat(harness.commits()).isEqualTo(2); // 上传一次、删除一次
        assertThat(harness.storage.deleted).containsExactly("uploads/" + document.id());
        assertThatThrownBy(() -> service.delete(ALICE, "missing")).isInstanceOf(DocumentNotFoundException.class);
    }

    @Test
    @DisplayName("重新索引：FAILED 重置三态并重投任务")
    void reindexFailedDocumentResetsAndEnqueues() {
        Harness harness = new Harness();
        Document document = harness.ingestAsAlice("a.txt", "hello world");
        harness.repository.added.set(0, document.markFailed("boom"));

        Document result = harness.service.reindex(ALICE, document.id());

        assertThat(result.status()).isEqualTo(DocumentStatus.PENDING);
        assertThat(result.chunkCount()).isNull();
        assertThat(result.errorMessage()).isNull();
        assertThat(result.indexedAt()).isNull();
        assertThat(harness.outbox.added).containsExactly(
                document.id(), document.id());
        assertThat(harness.commits()).isEqualTo(2);
    }

    @Test
    @DisplayName("健康的文档也允许重切（换 CHUNK_SIZE / 嵌入模型后整篇重建）")
    void reindexSuccessDocumentIsAllowed() {
        Harness harness = new Harness();
        Document document = harness.ingestAsAlice("a.txt", "hello world");
        harness.repository.added.set(0, document.markIndexed(3, Instant.now()));

        assertThat(harness.service.reindex(ALICE, document.id()).status()).isEqualTo(DocumentStatus.PENDING);
        assertThat(harness.outbox.added).hasSize(2);
        assertThat(harness.commits()).isEqualTo(2);
    }

    @Test
    @DisplayName("PENDING（正在处理）拒绝叠任务")
    void reindexPendingDocumentIsRejected() {
        Harness harness = new Harness();
        Document document = harness.ingestAsAlice("a.txt", "hello world");

        assertThatThrownBy(() -> harness.service.reindex(ALICE, document.id()))
                .isInstanceOf(IllegalArgumentException.class);

        assertThat(harness.outbox.added).hasSize(1); // 只有上传那一条
        assertThat(harness.commits()).isEqualTo(1);
    }

    @Test
    @DisplayName("重索引不存在的文档：404 语义")
    void reindexMissingDocumentRaises() {
        Harness harness = new Harness();

        assertThatThrownBy(() -> harness.service.reindex(ALICE, "missing"))
                .isInstanceOf(DocumentNotFoundException.class);
    }
}
