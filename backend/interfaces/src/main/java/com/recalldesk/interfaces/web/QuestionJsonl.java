package com.recalldesk.interfaces.web;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.recalldesk.application.eval.dto.ImportedQuestion;
import com.recalldesk.application.eval.dto.ImportedQuestion.ImportedChunk;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

/**
 * 题目文件（jsonl）的读取与形状校验：一行一道题，行内是一个 JSON 对象。
 *
 * 解析放在 interfaces 层是因为这活儿的全部内容就是「一种 HTTP 传输形状」：Jackson 只在这一层出现，
 * 应用层收的是已经立好的 {@link ImportedQuestion}，它不知道也不需要知道题目是按行喂的还是
 * 按数组喂的。形状之外什么都不判——文档归属、块号在不在范围内都是 {@code EvalService} 的事。
 *
 * 错误按行收齐再一次性报：传错格式的文件时，「第一个错误就抛」意味着改一行试一次、来回十几次。
 */
public final class QuestionJsonl {

    /** 一行的合法键：题面与金标。 */
    private static final List<String> ITEM_KEYS = List.of("query", "evidence");
    /** 一个金标的合法键：文档与块号。 */
    private static final List<String> QUOTE_KEYS = List.of("document_id", "chunk_index");
    /** 报错清单的封顶：一整份文件行行都错时，几百条消息会把有用那几条挤出屏幕。 */
    private static final int MAX_REPORTED_PROBLEMS = 10;

    private QuestionJsonl() {}

    /**
     * 解析结果：读得出形状的题 + 读不出来的原因。
     *
     * 两者可以同时非空——第 3 行坏了不影响第 1、2 行的形状已经立起来，但整份文件必须一起拒。
     */
    public record Parsed(List<ImportedQuestion> questions, List<String> problems) {}

    public static Parsed parse(ObjectMapper mapper, byte[] content) {
        List<String> problems = new ArrayList<>();
        String text;
        try {
            text = decodeUtf8(content);
        } catch (CharacterCodingException exc) {
            return new Parsed(List.of(), List.of("文件必须是 UTF-8 文本"));
        }
        List<ImportedQuestion> questions = new ArrayList<>();
        // \R 覆盖 LF / CRLF / 孤立 CR：Windows 记事本存出来的文件也能传
        String[] lines = stripBom(text).split("\\R", -1);
        for (int index = 0; index < lines.length; index++) {
            String line = lines[index];
            if (line.isBlank()) {
                continue;
            }
            // 报行号而不是报第几题：用户手上有的是那份文件，行号能直接跳过去
            String label = "第 " + (index + 1) + " 行";
            JsonNode node = readObject(mapper, line, label, problems);
            if (node == null) {
                continue;
            }
            int problemsBefore = problems.size();
            ImportedQuestion question = toQuestion(node, label, problems);
            if (problems.size() == problemsBefore) {
                questions.add(question);
            }
        }
        return new Parsed(questions, problems);
    }

    private static JsonNode readObject(ObjectMapper mapper, String line, String label, List<String> problems) {
        JsonNode node;
        try {
            node = mapper.readTree(line);
        } catch (JsonProcessingException exc) {
            // 整行的 JSON 都读不出来：最常见的成因是把一整个 JSON 数组拍平了传
            problems.add(label + " 不是合法的 JSON：" + rootMessage(exc));
            return null;
        }
        if (node == null || !node.isObject()) {
            problems.add(label + " 不是 JSON 对象（每行要形如 {\"query\": \"…\", \"evidence\": [...]}）");
            return null;
        }
        unknownKeys(node, ITEM_KEYS, label, problems);
        return node;
    }

    /** 立不起形状时也返回一个对象（题面为空串）：调用方按 problems 是否变多来决定收不收这一行。 */
    private static ImportedQuestion toQuestion(JsonNode node, String label, List<String> problems) {
        String query = text(node, "query", label, problems);
        JsonNode evidence = node.get("evidence");
        if (evidence == null) {
            problems.add(label + " 缺 evidence（这道题的金标 chunk）");
            return new ImportedQuestion(query == null ? "" : query, List.of());
        }
        if (!evidence.isArray()) {
            problems.add(label + " 的 evidence 不是数组");
            return new ImportedQuestion(query == null ? "" : query, List.of());
        }
        List<ImportedChunk> chunks = new ArrayList<>();
        for (int position = 0; position < evidence.size(); position++) {
            String where = label + " 的第 " + (position + 1) + " 个金标";
            JsonNode entry = evidence.get(position);
            if (!entry.isObject()) {
                problems.add(where + " 不是 JSON 对象");
                continue;
            }
            unknownKeys(entry, QUOTE_KEYS, where, problems);
            String documentId = text(entry, "document_id", where, problems);
            Integer chunkIndex = integer(entry, "chunk_index", where, problems);
            if (documentId != null && chunkIndex != null) {
                chunks.add(new ImportedChunk(documentId, chunkIndex));
            }
        }
        // 空 evidence 数组在这里放过（形状没错），由 EvalService 按语义报「没有任何金标」；
        // 部分金标有形状问题时整行不进清单，否则报错行号与实际落库的题数会错开
        return new ImportedQuestion(query == null ? "" : query, chunks.size() == evidence.size() ? chunks : List.of());
    }

    /** 给了不认识的键要说话：把 quote 打成 quotes，静默通过后就是一句「没有任何出处引文」。 */
    private static void unknownKeys(JsonNode node, List<String> allowed, String label, List<String> problems) {
        List<String> extras = new ArrayList<>();
        for (Iterator<String> names = node.fieldNames(); names.hasNext(); ) {
            String name = names.next();
            if (!allowed.contains(name)) {
                extras.add(name);
            }
        }
        if (!extras.isEmpty()) {
            problems.add(label + " 有不认识的键：" + String.join("、", extras)
                    + "（只认 " + String.join("、", allowed) + "）");
        }
    }

    /** 取一个非负整数字段；缺、null、不是整数、为负都记一条问题并返回 null。 */
    private static Integer integer(JsonNode node, String field, String label, List<String> problems) {
        JsonNode value = node.get(field);
        if (value == null || value.isNull()) {
            problems.add(label + " 缺 " + field);
            return null;
        }
        if (!value.isInt()) {
            problems.add(label + " 的 " + field + " 不是整数");
            return null;
        }
        int number = value.asInt();
        if (number < 0) {
            problems.add(label + " 的 " + field + " 不能为负: " + number);
            return null;
        }
        return number;
    }

    /** 取一个非空的字符串字段；缺、null、不是字符串、纯空白都记一条问题并返回 null。 */
    private static String text(JsonNode node, String field, String label, List<String> problems) {
        JsonNode value = node.get(field);
        if (value == null || value.isNull()) {
            problems.add(label + " 缺 " + field);
            return null;
        }
        if (!value.isTextual()) {
            problems.add(label + " 的 " + field + " 不是字符串");
            return null;
        }
        String text = value.asText();
        if (text.isBlank()) {
            problems.add(label + " 的 " + field + " 是空串");
            return null;
        }
        return text;
    }

    /** 报错清单的封顶：一整份文件行行都错时，几百条消息会把有用那几条挤出屏幕。 */
    public static String describe(List<String> problems) {
        StringBuilder text = new StringBuilder("题目文件读不出来：\n");
        for (int index = 0; index < Math.min(problems.size(), MAX_REPORTED_PROBLEMS); index++) {
            text.append(index + 1).append(". ").append(problems.get(index)).append('\n');
        }
        if (problems.size() > MAX_REPORTED_PROBLEMS) {
            text.append("……还有 ").append(problems.size() - MAX_REPORTED_PROBLEMS).append(" 条同类问题");
        }
        return text.toString().strip();
    }

    /** Jackson 的原始消息带着「(63 chars)」这类行内偏移，只留冒号前那句人看得懂的。 */
    private static String rootMessage(JsonProcessingException exc) {
        String message = exc.getOriginalMessage();
        if (message == null || message.isEmpty()) {
            return exc.getMessage();
        }
        int colon = message.indexOf(':');
        return colon > 0 ? message.substring(0, colon).strip() : message;
    }

    private static String decodeUtf8(byte[] content) throws CharacterCodingException {
        return StandardCharsets.UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(content))
                .toString();
    }

    /** 记事本「另存为 UTF-8」会带 BOM，它不是内容的一部分。 */
    private static String stripBom(String text) {
        return text.startsWith(String.valueOf((char) 0xFEFF)) ? text.substring(1) : text;
    }
}
