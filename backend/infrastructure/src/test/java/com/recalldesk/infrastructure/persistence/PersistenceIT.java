package com.recalldesk.infrastructure.persistence;

import static org.assertj.core.api.Assertions.assertThat;

import com.recalldesk.domain.Page;
import com.recalldesk.domain.documents.Document;
import com.recalldesk.domain.documents.DocumentStatus;
import com.recalldesk.domain.documents.DocumentTask;
import com.recalldesk.domain.documents.DocumentTaskStatus;
import com.recalldesk.domain.port.persistence.DocumentRepository;
import com.recalldesk.domain.port.persistence.DocumentTaskRepository;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ContextConfiguration;

/**
 * 真库跑通 documents / document_tasks（手动拉起：{@code -Dtest=PersistenceIT}）。
 *
 * 单测测不到的是 MyBatis↔PG 这一层的胶水——MP 的 camelCase→snake_case 猜错列名、
 * Instant 没被 TypeHandler 接住、FOR UPDATE SKIP LOCKED 的语法、DEFAULT now() 的列谁负责填，
 * 这些全只在真库上坏。归属谓词同样只在真库上验得准：别人的行是 SQL 里就没捞到，
 * 不是捞回来后被 java 筛掉。跑出来的痕迹按 uuid 收尾，不 TRUNCATE：库里有语料。
 */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.NONE,
        properties = {
            "spring.datasource.url=jdbc:postgresql://127.0.0.1:5435/anna_rag",
            "spring.datasource.username=rag",
            "spring.datasource.password=rag",
            "spring.datasource.driver-class-name=org.postgresql.Driver",
            "mybatis-plus.configuration.map-underscore-to-camel-case=true",
            "recalldesk.task.retry-backoff-base-seconds=30",
        })
@ContextConfiguration(classes = PersistenceIT.TestApp.class)
class PersistenceIT {

    @Configuration(proxyBeanMethods = false)
    @EnableAutoConfiguration
    @Import({MyBatisDocumentRepository.class, MyBatisDocumentTaskRepository.class})
    static class TestApp {}

    @Autowired
    private DocumentRepository documents;

    @Autowired
    private DocumentTaskRepository tasks;

    @Autowired
    private JdbcTemplate jdbc;

    @Test
    void documentRoundTrip() {
        String alice = seedUser();
        String bob = seedUser();
        String documentId = UUID.randomUUID().toString();
        String otherId = UUID.randomUUID().toString();
        try {
            documents.add(new Document(
                    documentId, alice, "it.doc", "it/obj", 12L, "text/plain",
                    DocumentStatus.PENDING, null, null, null, null));

            // created_at 由库的 DEFAULT now() 填，读回来必须是 Instant
            Document loaded = documents.get(documentId).orElseThrow();
            assertThat(loaded.userId()).isEqualTo(alice);
            assertThat(loaded.createdAt()).isBetween(Instant.now().minusSeconds(120), Instant.now().plusSeconds(10));
            assertThat(loaded.sizeBytes()).isEqualTo(12L);
            assertThat(loaded.mediaType()).isEqualTo("text/plain");
            assertThat(loaded.status()).isEqualTo(DocumentStatus.PENDING);
            assertThat(loaded.chunkCount()).isNull();

            assertThat(documents.get("查不到就空")).isEmpty();
            // worker 走 get(id)（归属从行里读出），对外读走 getOwned：越权与不存在同一个答案
            assertThat(documents.getOwned(alice, documentId)).isPresent();
            assertThat(documents.getOwned(bob, documentId)).isEmpty();

            documents.update(loaded.markIndexed(7, Instant.now()));
            Document indexed = documents.get(documentId).orElseThrow();
            assertThat(indexed.status()).isEqualTo(DocumentStatus.SUCCESS);
            assertThat(indexed.chunkCount()).isEqualTo(7);
            assertThat(indexed.indexedAt()).isNotNull();

            documents.add(new Document(
                    otherId, alice, "it2.doc", "it/obj2", 3L, null,
                    DocumentStatus.PENDING, null, null, null, null));

            Page<Document> page = documents.list(alice, 1, 5);
            assertThat(page.total()).isEqualTo(2);
            assertThat(page.items()).hasSize(2).extracting(Document::id).contains(documentId, otherId);
            assertThat(page.items()).allSatisfy(item -> assertThat(item.userId()).isEqualTo(alice));
            assertThat(page.items()).extracting(Document::createdAt).isSortedAccordingTo(
                    java.util.Comparator.reverseOrder());
            // 分页只看得见自己的：bob 一行都没有
            assertThat(documents.list(bob, 1, 5).total()).isZero();

            // 删除同样带归属谓词：别人删不掉，自己删了才算数
            assertThat(documents.delete(bob, otherId)).isFalse();
            assertThat(documents.delete(alice, otherId)).isTrue();
            assertThat(documents.delete(alice, otherId)).isFalse();
        } finally {
            jdbc.update("DELETE FROM document_tasks WHERE document_id IN (?, ?)", documentId, otherId);
            jdbc.update("DELETE FROM documents WHERE id IN (?, ?)", documentId, otherId);
            jdbc.update("DELETE FROM users WHERE id IN (?, ?)", alice, bob);
        }
    }

    @Test
    void outboxTaskStateMachine() {
        String alice = seedUser();
        String documentId = UUID.randomUUID().toString();
        documents.add(new Document(
                documentId, alice, "it-task.doc", "it/obj", 1L, null,
                DocumentStatus.PENDING, null, null, null, null));
        try {
            tasks.add(documentId);
            String taskId = taskRowId(jdbc, documentId);

            DocumentTask task = tasks.get(taskId).orElseThrow();
            assertThat(task.status()).isEqualTo(DocumentTaskStatus.PENDING);
            assertThat(task.attempts()).isZero();
            assertThat(task.createdAt()).isNotNull();

            List<DocumentTask> pending = tasks.listPending(500);
            assertThat(pending).extracting(DocumentTask::id).contains(taskId);

            tasks.markQueued(taskId);
            DocumentTask queued = tasks.get(taskId).orElseThrow();
            assertThat(queued.status()).isEqualTo(DocumentTaskStatus.QUEUE);
            assertThat(queued.queuedAt()).isNotNull();
            // 投递后不该再被出箱捞起来
            assertThat(tasks.listPending(500)).extracting(DocumentTask::id).doesNotContain(taskId);

            tasks.recordFailure(taskId, "x".repeat(3000));
            DocumentTask retried = tasks.get(taskId).orElseThrow();
            assertThat(retried.status()).isEqualTo(DocumentTaskStatus.PENDING);
            assertThat(retried.attempts()).isEqualTo(1);
            assertThat(retried.lastError()).hasSize(2000);
            assertThat(retried.queuedAt()).isNotNull();
            assertThat(delaySeconds(jdbc, taskId)).isBetween(25L, 35L);

            // 第二次失败的退避翻倍；退避未到之前 listPending 不该捞到它
            tasks.recordFailure(taskId, "第二次失败");
            assertThat(delaySeconds(jdbc, taskId)).isBetween(55L, 65L);
            assertThat(tasks.listPending(500)).extracting(DocumentTask::id).doesNotContain(taskId);

            tasks.markSuccess(taskId);
            assertThat(tasks.get(taskId).orElseThrow().status()).isEqualTo(DocumentTaskStatus.SUCCESS);
            tasks.markFailed(taskId);
            assertThat(tasks.get(taskId).orElseThrow().status()).isEqualTo(DocumentTaskStatus.FAILED);
        } finally {
            jdbc.update("DELETE FROM document_tasks WHERE document_id = ?", documentId);
            jdbc.update("DELETE FROM documents WHERE id = ?", documentId);
            jdbc.update("DELETE FROM users WHERE id = ?", alice);
        }
    }

    /** documents.user_id 是外键，测试数据得先有一个真用户。 */
    private String seedUser() {
        String id = UUID.randomUUID().toString();
        jdbc.update("INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
                id, "it-" + id, "pbkdf2$it-placeholder");
        return id;
    }

    private static String taskRowId(JdbcTemplate jdbc, String documentId) {
        return jdbc.queryForObject(
                "SELECT id FROM document_tasks WHERE document_id = ? ORDER BY created_at, id", String.class,
                documentId);
    }

    /** 退避列不在领域实体上（它只描述"下一次什么时候能投"），断言直接读列。 */
    private static long delaySeconds(JdbcTemplate jdbc, String taskId) {
        Instant at = jdbc.queryForObject(
                "SELECT next_retry_at FROM document_tasks WHERE id = ?", Instant.class, taskId);
        return Duration.between(Instant.now(), at).getSeconds();
    }
}
