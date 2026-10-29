package com.recalldesk.application.eval;

import com.recalldesk.application.eval.dto.EvalTestSetDetail;
import com.recalldesk.domain.documents.Document;
import com.recalldesk.domain.eval.EvalTestSet;
import com.recalldesk.domain.eval.EvalTestSetItem;
import com.recalldesk.domain.eval.EvidenceQuote;
import com.recalldesk.application.eval.dto.ImportedQuestion;
import com.recalldesk.application.eval.dto.ImportedQuestion.ImportedChunk;
import com.recalldesk.domain.exception.eval.TestSetNotFoundException;
import com.recalldesk.domain.port.ops.UnitOfWork;
import com.recalldesk.domain.port.persistence.ChunkIndex;
import com.recalldesk.domain.port.persistence.DocumentRepository;
import com.recalldesk.domain.port.persistence.EvalRepository;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.stereotype.Component;

/**
 * 测试集用例编排：建集、导入题目、列表、详情、删除。
 *
 * 题目由用户提供，导入是**同步**的：一次 HTTP 请求内解析完引文、落库、返回详情，
 * 没有后台链路参与。所以库里不存在「半成品题目」，解析失败的代价是整次上传被拒——
 * 用户改一句引文重传就行，比留一堆解析不出来的题在那儿等人清理诚实。
 *
 * 为什么整批拒绝而不是好的收下、坏的报个警告：一个测试集的分母必须由人明确知道是几道题。
 * 收下 90 题悄悄丢掉 10 题，下一次 run 的数字就对不上任何人的预期了。
 */
@Component
public class EvalService {

    public static final String DEFAULT_TESTSET_NAME = "未命名测试集";
    /** 一题最多几段引文：多跳题现实里 2-3 段，5 是防手滑的天花板。 */
    public static final int MAX_EVIDENCE_QUOTES_PER_ITEM = 5;
    /** 一次上传最多多少题：解析要在请求内读完这些文档的全部分块，别拿它当批处理入口。 */
    public static final int MAX_ITEMS_PER_UPLOAD = 500;
    /** 报错最多列几条：整份 jsonl 传错格式时，几百行报错会把有用那一条挤出屏幕。 */
    private static final int MAX_REPORTED_PROBLEMS = 10;

    private final EvalRepository evals;
    private final DocumentRepository documents;
    private final ChunkIndex chunkIndex;
    private final UnitOfWork unitOfWork;

    public EvalService(
            EvalRepository evals,
            DocumentRepository documents,
            ChunkIndex chunkIndex,
            UnitOfWork unitOfWork) {
        this.evals = evals;
        this.documents = documents;
        this.chunkIndex = chunkIndex;
        this.unitOfWork = unitOfWork;
    }

    /** 只建一个空测试集：题目靠 importItems 往里加。 */
    public EvalTestSetDetail createTestSet(String userId, String name) {
        String testSetId = UUID.randomUUID().toString();
        String trimmed = name == null ? "" : name.strip();
        String resolvedName = trimmed.isEmpty() ? DEFAULT_TESTSET_NAME : trimmed;
        unitOfWork.execute(() -> evals.createTestSet(testSetId, userId, resolvedName));
        return getTestSet(userId, testSetId);
    }

    /**
     * 导入题目：逐条解析引文落点，全部解析得出来才在同一事务里落库。
     *
     * 任何一条不合格就整批拒绝，问题清单里说清是第几题的哪句引文在哪篇文档里找不到。
     * 空清单什么都不写（与 addItems 时代同一条规矩：别让一次空上传改动集的状态）。
     */
    public EvalTestSetDetail importItems(String userId, String testSetId, List<ImportedQuestion> questions) {
        requireTestSet(userId, testSetId);
        if (questions.isEmpty()) {
            return getTestSet(userId, testSetId);
        }
        if (questions.size() > MAX_ITEMS_PER_UPLOAD) {
            throw new IllegalArgumentException(
                    "一次最多导入 " + MAX_ITEMS_PER_UPLOAD + " 道题（这份有 " + questions.size() + " 道）");
        }

        // 一篇文档的块数只查一次：一次上传的金标通常集中在少数几篇文档上
        Map<String, Integer> chunkCounts = new LinkedHashMap<>();
        List<String> problems = new ArrayList<>();
        List<EvalTestSetItem> items = new ArrayList<>(questions.size());

        for (int number = 1; number <= questions.size(); number++) {
            ImportedQuestion question = questions.get(number - 1);
            String label = "第 " + number + " 题（" + shorten(question.query()) + "）";
            if (question.chunks().isEmpty()) {
                problems.add(label + " 没有任何金标 chunk");
                continue;
            }
            if (question.chunks().size() > MAX_EVIDENCE_QUOTES_PER_ITEM) {
                problems.add(label + " 有 " + question.chunks().size() + " 个金标，超过上限 "
                        + MAX_EVIDENCE_QUOTES_PER_ITEM + " 个");
                continue;
            }

            String itemId = UUID.randomUUID().toString();
            List<EvidenceQuote> evidence = new ArrayList<>(question.chunks().size());
            for (int ordinal = 0; ordinal < question.chunks().size(); ordinal++) {
                ImportedChunk chunk = question.chunks().get(ordinal);
                Document document = ownedDocument(userId, chunk.documentId(), problems, label);
                if (document == null) {
                    continue;
                }
                if (chunk.chunkIndex() < 0) {
                    problems.add(label + " 的 chunk_index 不能为负: " + chunk.chunkIndex());
                    continue;
                }
                int chunkCount = chunkCounts.computeIfAbsent(document.id(),
                        id -> chunkIndex.getDocumentChunks(id).size());
                if (chunkCount == 0) {
                    problems.add(label + " 的出处文档「" + document.name() + "」还没有索引块，等索引完成后再导");
                    continue;
                }
                if (chunk.chunkIndex() >= chunkCount) {
                    problems.add(label + " 指定的块 " + chunk.chunkIndex() + " 超出文档「"
                            + document.name() + "」的范围（共 " + chunkCount + " 块）");
                    continue;
                }
                evidence.add(new EvidenceQuote(
                        UUID.randomUUID().toString(), itemId, document.id(), chunk.chunkIndex(), ordinal));
            }
            if (evidence.size() == question.chunks().size()) {
                items.add(new EvalTestSetItem(itemId, question.query(), evidence));
            }
        }

        if (!problems.isEmpty()) {
            throw new IllegalArgumentException(describe(problems));
        }
        unitOfWork.execute(() -> evals.addItems(testSetId, items));
        return getTestSet(userId, testSetId);
    }

    /** 评测集列表（含题目数），按创建时间降序。 */
    public List<EvalTestSet> listTestSets(String userId) {
        return evals.listTestSets(userId);
    }

    /** 单个评测集 + 它的全部题目。 */
    public EvalTestSetDetail getTestSet(String userId, String testSetId) {
        EvalTestSet testSet = requireTestSet(userId, testSetId);
        return new EvalTestSetDetail(testSet, evals.listTestSetItems(testSetId));
    }

    /** 删除评测集：题目、引文与它名下所有 run 随级联一起走。 */
    public void deleteTestSet(String userId, String testSetId) {
        requireTestSet(userId, testSetId);
        unitOfWork.execute(() -> evals.deleteTestSet(userId, testSetId));
    }

    private EvalTestSet requireTestSet(String userId, String testSetId) {
        return evals.getTestSet(userId, testSetId).orElseThrow(() -> new TestSetNotFoundException(testSetId));
    }

    private Document ownedDocument(
            String userId, String documentId, List<String> problems, String label) {
        if (documentId == null || documentId.isBlank()) {
            problems.add(label + " 有一段引文没给出 document_id");
            return null;
        }
        Document document = documents.getOwned(userId, documentId).orElse(null);
        if (document == null) {
            // 「不存在」与「不是你的」同一个说法：这个接口不该告诉调用者别人的文档 id 长什么样
            problems.add(label + " 的文档 " + documentId + " 不存在（或不属于你）");
        }
        return document;
    }

    private static String describe(List<String> problems) {
        List<String> shown = new ArrayList<>(new LinkedHashSet<>(problems));
        StringBuilder text = new StringBuilder("题目导入失败：\n");
        for (int i = 0; i < Math.min(shown.size(), MAX_REPORTED_PROBLEMS); i++) {
            text.append(i + 1).append(". ").append(shown.get(i)).append('\n');
        }
        if (shown.size() > MAX_REPORTED_PROBLEMS) {
            text.append("……还有 ").append(shown.size() - MAX_REPORTED_PROBLEMS).append(" 条同类问题");
        }
        return text.toString().strip();
    }

    /** 报错里引用原文只留一小截：整段引文会让清单没法读。 */
    private static String shorten(String text) {
        if (text == null) {
            return "（空）";
        }
        String single = text.replaceAll("\\s+", " ").strip();
        return single.length() <= 40 ? "「" + single + "」" : "「" + single.substring(0, 40) + "…」";
    }
}
