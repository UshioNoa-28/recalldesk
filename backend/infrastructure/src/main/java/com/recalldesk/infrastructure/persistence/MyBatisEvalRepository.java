package com.recalldesk.infrastructure.persistence;

import com.recalldesk.domain.eval.EvalTestSet;
import com.recalldesk.domain.eval.EvalTestSetItem;
import com.recalldesk.domain.eval.EvidenceQuote;
import com.recalldesk.domain.port.persistence.EvalRepository;
import com.recalldesk.infrastructure.persistence.mapper.EvalEvidenceMapper;
import com.recalldesk.infrastructure.persistence.mapper.EvalTestSetItemMapper;
import com.recalldesk.infrastructure.persistence.mapper.EvalTestSetMapper;
import com.recalldesk.infrastructure.persistence.row.EvalEvidenceRow;
import com.recalldesk.infrastructure.persistence.row.EvalTestSetItemRow;
import com.recalldesk.infrastructure.persistence.row.EvalTestSetRow;
import com.recalldesk.infrastructure.persistence.row.TestSetItemCountRow;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.stereotype.Repository;

/** 评测集与题目的 MyBatis-Plus 实现：只挂调用方的事务，自己不提交。 */
@Repository
public class MyBatisEvalRepository implements EvalRepository {

    private final EvalTestSetMapper testSets;
    private final EvalTestSetItemMapper items;
    private final EvalEvidenceMapper evidence;

    public MyBatisEvalRepository(
            EvalTestSetMapper testSets, EvalTestSetItemMapper items, EvalEvidenceMapper evidence) {
        this.testSets = testSets;
        this.items = items;
        this.evidence = evidence;
    }

    // ---- testsets ----

    @Override
    public void createTestSet(String testSetId, String userId, String name) {
        EvalTestSetRow row = new EvalTestSetRow();
        row.setId(testSetId);
        row.setUserId(userId);
        row.setName(name);
        testSets.insert(row);
    }

    @Override
    public Optional<EvalTestSet> getTestSet(String userId, String testSetId) {
        EvalTestSetRow row = testSets.selectById(testSetId);
        // 归属在应用层判等而不是靠 SQL 过滤：selectById 已经拿了一行，
        // 再比一次 user_id 比再来一条「按 id+user 查」的语句便宜，也不会漏判
        if (row == null || !userId.equals(row.getUserId())) {
            return Optional.empty();
        }
        return Optional.of(row.toDomain(countItems(userId, List.of(testSetId)).getOrDefault(testSetId, 0)));
    }

    @Override
    public List<EvalTestSet> listTestSets(String userId) {
        List<EvalTestSetRow> rows = testSets.listByUser(userId);
        Map<String, Integer> counts = countItems(
                userId, rows.stream().map(EvalTestSetRow::getId).toList());
        return rows.stream().map(row -> row.toDomain(counts.getOrDefault(row.getId(), 0))).toList();
    }

    @Override
    public void deleteTestSet(String userId, String testSetId) {
        // deleteById 不看归属，越权删除会一声不响地成功，所以先读一遍确认是自己的
        if (getTestSet(userId, testSetId).isPresent()) {
            testSets.deleteById(testSetId);
        }
    }

    // ---- items ----

    @Override
    public void addItems(String testSetId, List<EvalTestSetItem> newItems) {
        for (EvalTestSetItem item : newItems) {
            EvalTestSetItemRow row = new EvalTestSetItemRow();
            row.setId(item.id());
            row.setTestsetId(testSetId);
            row.setQuery(item.query());
            items.insert(row);

            for (EvidenceQuote quote : item.evidence()) {
                evidence.insert(EvalEvidenceRow.from(quote));
            }
        }
    }

    @Override
    public List<EvalTestSetItem> listTestSetItems(String testSetId) {
        List<EvalTestSetItemRow> rows = items.listByTestSet(testSetId);
        Map<String, List<EvidenceQuote>> byItem =
                evidenceByItem(rows.stream().map(EvalTestSetItemRow::getId).toList());
        return rows.stream()
                .map(row -> new EvalTestSetItem(
                        row.getId(), row.getQuery(), byItem.getOrDefault(row.getId(), List.of())))
                .toList();
    }

    @Override
    public Optional<EvalTestSetItem> getItem(String itemId) {
        EvalTestSetItemRow row = items.selectById(itemId);
        if (row == null) {
            return Optional.empty();
        }
        return Optional.of(new EvalTestSetItem(
                row.getId(), row.getQuery(),
                evidenceByItem(List.of(itemId)).getOrDefault(itemId, List.of())));
    }

    @Override
    public int deleteItemsReferencingDocument(String documentId) {
        return items.deleteReferencingDocument(documentId);
    }

    /** 一次 IN 查询拿回一批题目的金标，按 item_id 归堆——不给逐题 N+1 的机会。 */
    private Map<String, List<EvidenceQuote>> evidenceByItem(List<String> itemIds) {
        Map<String, List<EvidenceQuote>> byItem = new HashMap<>();
        if (itemIds.isEmpty()) {
            return byItem;
        }
        for (EvalEvidenceRow row : evidence.listByItems(itemIds)) {
            byItem.computeIfAbsent(row.getItemId(), key -> new ArrayList<>())
                    .add(row.toDomain());
        }
        return byItem;
    }

    private Map<String, Integer> countItems(String userId, List<String> testSetIds) {
        Map<String, Integer> counts = new HashMap<>();
        if (testSetIds.isEmpty()) {
            return counts; // 空 IN () 是语法错误，不是空结果
        }
        for (TestSetItemCountRow row : testSets.countItems(userId, testSetIds)) {
            counts.put(row.getTestsetId(), row.getTotal() == null ? 0 : row.getTotal());
        }
        return counts;
    }

}
