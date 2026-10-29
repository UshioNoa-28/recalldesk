package com.recalldesk.infrastructure.persistence;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.recalldesk.domain.eval.EvalTestSet;
import com.recalldesk.domain.eval.EvalTestSetItem;
import com.recalldesk.domain.eval.EvidenceQuote;
import com.recalldesk.domain.port.persistence.EvalRepository;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ContextConfiguration;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * 评测集/题目/引文三张表的真库用例（手动拉起：{@code -Dtest=EvalPersistenceIT}）。
 *
 * 覆盖的是端口里那些"语义写在注释里"的行为：归属过滤、题数计数、引文的 ordinal 与
 * 归一化比对键、派生坐标的写回、牵连删题。引文→documents 是 RESTRICT，测试数据必须先落 documents。
 *
 * 每个用例一个事务、跑完回滚：库里那份语料删不起。用例因此只写新行、不靠删旧行收尾
 * （DELETE 被回滚后"删干净了"的断言永远成立，等于没测）。撞外键那步单独跑在 savepoint 里：
 * 约束报错会把当前事务标成 aborted，回滚只回到那里，用例还能继续往下断。
 */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.NONE,
        properties = {
            "spring.datasource.url=jdbc:postgresql://127.0.0.1:5435/anna_rag",
            "spring.datasource.username=rag",
            "spring.datasource.password=rag",
            "spring.datasource.driver-class-name=org.postgresql.Driver",
            "mybatis-plus.configuration.map-underscore-to-camel-case=true",
        })
@Transactional
@ContextConfiguration(classes = EvalPersistenceIT.TestApp.class)
class EvalPersistenceIT {

    @Configuration(proxyBeanMethods = false)
    @EnableAutoConfiguration
    @Import(MyBatisEvalRepository.class)
    static class TestApp {}

    @Autowired
    private EvalRepository evals;

    @Autowired
    private JdbcTemplate jdbc;

    @Autowired
    private PlatformTransactionManager transactionManager;

    @Test
    void testsetIsOwnedAndCountsItsItems() {
        String alice = seedUser();
        String bob = seedUser();
        String testSetId = UUID.randomUUID().toString();
        evals.createTestSet(testSetId, alice, "it-testset");

        EvalTestSet created = evals.getTestSet(alice, testSetId).orElseThrow();
        assertThat(created.userId()).isEqualTo(alice);
        assertThat(created.name()).isEqualTo("it-testset");
        assertThat(created.createdAt()).isNotNull();
        assertThat(created.itemCount()).isZero();

        // 越权读：别人的集与不存在的集同一个答案（service 层据此翻 404，而不是 403）
        assertThat(evals.getTestSet(bob, testSetId)).isEmpty();
        assertThat(evals.listTestSets(bob)).extracting(EvalTestSet::id).doesNotContain(testSetId);
        assertThat(evals.listTestSets(alice)).extracting(EvalTestSet::id).contains(testSetId);

        // 越权删：先读后删，不是自己的什么都不动
        evals.deleteTestSet(bob, testSetId);
        assertThat(evals.getTestSet(alice, testSetId)).isPresent();

        evals.addItems(testSetId, List.of(
                item(UUID.randomUUID().toString(), "豆腐有多少蛋白质？",
                        quote(UUID.randomUUID().toString(), seedDocument(alice), 0, "豆腐的蛋白质含量约为八克")),
                item(UUID.randomUUID().toString(), "牛奶补钙吗？",
                        quote(UUID.randomUUID().toString(), seedDocument(alice), 0, "牛奶的钙含量很高"))));
        assertThat(evals.getTestSet(alice, testSetId).orElseThrow().itemCount()).isEqualTo(2);

        evals.deleteTestSet(alice, testSetId);
        assertThat(evals.getTestSet(alice, testSetId)).isEmpty();
        // 级联：集没了题目与引文跟着没（不留下对不上号的行）
        assertThat(jdbc.queryForObject(
                "SELECT count(*) FROM eval_testset_items WHERE testset_id = ?", Integer.class, testSetId)).isZero();
    }

    @Test
    void evidenceIsWrittenAsOneRowPerQuoteWithItsDerivedCoordinates() {
        String alice = seedUser();
        String testSetId = UUID.randomUUID().toString();
        String documentId = seedDocument(alice);
        evals.createTestSet(testSetId, alice, "it-evidence");

        // 一道多跳题：两段引文， ordinal 按拼装顺序；每段引文各落 1~2 块
        String itemId = UUID.randomUUID().toString();
        String first = UUID.randomUUID().toString();
        String second = UUID.randomUUID().toString();
        evals.addItems(testSetId, List.of(item(itemId, "豆腐和牛奶哪个更营养？",
                quote(first, documentId, 0, "豆腐的蛋白质含量约为八克"),
                quote(second, documentId, 1, "牛奶的钙含量是每百克一百零四毫克"))));

        List<EvalTestSetItem> items = evals.listTestSetItems(testSetId);
        assertThat(items).extracting(EvalTestSetItem::id).containsExactly(itemId);
        EvalTestSetItem stored = items.getFirst();
        assertThat(stored.evidence()).hasSize(2);
        // 读回来的就是写进去的块号
        assertThat(stored.evidence().getFirst().id()).isEqualTo(first);
        assertThat(stored.evidence().getFirst().chunkIndex()).isZero();
        assertThat(stored.evidence().get(1).ordinal()).isEqualTo(1);
        assertThat(stored.evidence().get(1).chunkIndex()).isEqualTo(1);

        assertThat(evals.getItem(itemId).orElseThrow().evidence()).hasSize(2);
        assertThat(evals.getItem("查不到就空")).isEmpty();
    }

    @Test
    void duplicateOrdinalWithinOneItemIsRejected() {
        String alice = seedUser();
        String testSetId = UUID.randomUUID().toString();
        String documentId = seedDocument(alice);
        evals.createTestSet(testSetId, alice, "it-ordinal");
        String itemId = UUID.randomUUID().toString();

        // (item_id, ordinal) 唯一：两段引文撞了序号就是写入端的 bug，库里不能留下两行说不清谁在前
        TransactionTemplate savepoint = nested();
        assertThatThrownBy(() -> savepoint.execute(status -> {
            evals.addItems(testSetId, List.of(
                    item(itemId, "重复序号",
                            quote(UUID.randomUUID().toString(), documentId, 0, "第一段话"),
                            quote(UUID.randomUUID().toString(), documentId, 0, "第二段话"))));
            return null;
        })).isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);

        // 回到 savepoint：这一题一个字都没落（引文行跟着题目一起没）
        assertThat(evals.listTestSetItems(testSetId)).isEmpty();
    }

    @Test
    void deletingDocumentPurgesEveryItemThatQuotedIt() {
        String alice = seedUser();
        String testSetId = UUID.randomUUID().toString();
        String doomed = seedDocument(alice);
        String other = seedDocument(alice);
        evals.createTestSet(testSetId, alice, "it-cleanup");
        evals.addItems(testSetId, List.of(
                item(UUID.randomUUID().toString(), "第一题", quote(UUID.randomUUID().toString(), doomed, 0, "第一段话")),
                item(UUID.randomUUID().toString(), "第二题",
                        quote(UUID.randomUUID().toString(), other, 0, "第二段话"),
                        quote(UUID.randomUUID().toString(), doomed, 1, "第三段话"))));
        assertThat(evals.listTestSetItems(testSetId)).hasSize(2);

        // 平权证据：只要引用了就算，删掉的是整道题而不是抹掉一个坐标
        assertThat(evals.deleteItemsReferencingDocument(doomed)).isEqualTo(2);
        assertThat(evals.listTestSetItems(testSetId)).isEmpty();
        assertThat(itemCountForDocument(doomed)).isZero();

        // 忘了上面那步的话，删文档会撞 evidence 的 RESTRICT 外键——有声保险丝
        String referenced = seedDocument(alice);
        evals.addItems(testSetId, List.of(item(UUID.randomUUID().toString(), "第四题",
                quote(UUID.randomUUID().toString(), referenced, 0, "第五段话"))));
        TransactionTemplate savepoint = nested();
        assertThatThrownBy(
                () -> savepoint.execute(status -> jdbc.update("DELETE FROM documents WHERE id = ?", referenced)))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);

        // 回滚只回到 savepoint：题还在，牵连删除把它清掉
        assertThat(itemCountForDocument(referenced)).isEqualTo(1);
        assertThat(evals.deleteItemsReferencingDocument(referenced)).isEqualTo(1);
        assertThat(itemCountForDocument(referenced)).isZero();
    }

    private TransactionTemplate nested() {
        TransactionTemplate savepoint = new TransactionTemplate(Objects.requireNonNull(transactionManager));
        savepoint.setPropagationBehavior(TransactionDefinition.PROPAGATION_NESTED);
        return savepoint;
    }

    private static EvalTestSetItem item(String id, String query, EvidenceQuote... evidence) {
        return new EvalTestSetItem(id, query, List.of(evidence));
    }

    private static EvidenceQuote quote(String id, String documentId, int ordinal, String text) {
        // 原文片段不再是模型的一部分：块号就取 ordinal，text 参数只为让用例读起来像在说"第几段话"
        return new EvidenceQuote(id, "item", documentId, ordinal, ordinal);
    }

    private int itemCountForDocument(String documentId) {
        return jdbc.queryForObject(
                "SELECT count(*) FROM eval_testset_items WHERE id IN "
                        + "(SELECT item_id FROM eval_testset_item_evidence WHERE document_id = ?)",
                Integer.class, documentId);
    }

    /** 归属是外键：先有一条真用户。 */
    private String seedUser() {
        String id = UUID.randomUUID().toString();
        jdbc.update("INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
                id, "it-" + id, "pbkdf2$it-placeholder");
        return id;
    }

    /** 引文表对 documents 有 RESTRICT 外键，测试数据得先有一条真文档。 */
    private String seedDocument(String userId) {
        String id = UUID.randomUUID().toString();
        jdbc.update(
                "INSERT INTO documents (id, user_id, name, storage_key, size_bytes, status) "
                        + "VALUES (?, ?, ?, ?, ?, 'pending')",
                id, userId, "it-eval.txt", "it/" + id, 1L);
        return id;
    }
}
