package com.recalldesk.infrastructure.text;

import com.recalldesk.domain.port.model.TextSplitter;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Function;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 句优先的分块器：llama-index {@code SentenceSplitter} 的 1:1 移植。
 *
 * 为什么手写而不是引一个 Java 分块库：本项目要的是"和已经跑通的切法同一条路"，
 * 换库就等于换切法，历史 run 的召回结果不再可比。这里逐条照搬它的算法
 * （split → merge → postprocess），只是把 tokenizer 换成"一个码点算一个 token"
 * ——中文一字一 token，chunk_size 于是就是字符数。
 *
 * 切分优先级：段落（\n\n\n）→ 句子（中英文句末标点）→ 子句正则 → 空格 → 单字。
 * 长句塞不进一块时优先整句挪到下一块，实在放不下才降到子句/单字级。
 */
public class SentenceTextSplitter implements TextSplitter {

    private static final String PARAGRAPH_SEPARATOR = "\n\n\n";
    private static final String WORD_SEPARATOR = " ";

    /** 中英文句末标点切句，标点跟随前一句。 */
    private static final Pattern SENTENCE = Pattern.compile(
            "(?<=[。！？.!?])\\s*", Pattern.UNICODE_CHARACTER_CLASS);

    /** 子句级兜底：以 , . ; ！？ 为界的短语块。 */
    private static final Pattern CLAUSE =
            Pattern.compile("[^,.;。？！]+[,.;。？！]?|[,.;。？！]");

    private final int chunkSize;
    private final int chunkOverlap;
    private final List<Function<String, List<String>>> splitFns;
    private final List<Function<String, List<String>>> subSentenceSplitFns;

    /**
     * 尺寸参数由组合根传入（配置只在组合根读一次，见 TextConfiguration）。
     * 构造期就把非法组合拦掉：重叠不小于块长会让 merge 永远无法推进。
     */
    public SentenceTextSplitter(int chunkSize, int chunkOverlap) {
        if (chunkSize <= 0) {
            throw new IllegalArgumentException("chunk_size 必须 > 0，收到 " + chunkSize);
        }
        if (chunkOverlap > chunkSize) {
            throw new IllegalArgumentException(
                    "chunk_overlap(" + chunkOverlap + ") 大于 chunk_size(" + chunkSize + ")，应当更小");
        }
        this.chunkSize = chunkSize;
        this.chunkOverlap = chunkOverlap;
        this.splitFns = List.of(
                splitBySeparatorKeeping(PARAGRAPH_SEPARATOR), SentenceTextSplitter::splitSentences);
        this.subSentenceSplitFns = List.of(
                text -> findAll(CLAUSE, text),
                splitBySeparatorKeeping(WORD_SEPARATOR),
                SentenceTextSplitter::splitByChar);
    }

    @Override
    public List<String> split(String text) {
        if (text.isEmpty()) {
            return List.of();
        }
        return postprocess(merge(splitInto(text, chunkSize), chunkSize));
    }

    /** 一块的候选片段：文本 + 它是不是"完整句子" + 它的 token 数。 */
    private record Split(String text, boolean sentence, int tokenSize) {}

    /** 递归切到每片都不超过 chunk_size；一整轮都切不开的那一片就带着超长继续走。 */
    private List<Split> splitInto(String text, int effectiveChunkSize) {
        int tokenSize = tokenSize(text);
        if (tokenSize <= effectiveChunkSize) {
            return List.of(new Split(text, true, tokenSize));
        }
        Splits found = getSplitsByFns(text);
        List<Split> splits = new ArrayList<>();
        for (String part : found.parts()) {
            int partSize = tokenSize(part);
            if (partSize <= effectiveChunkSize) {
                splits.add(new Split(part, found.sentence(), partSize));
            } else if (found.parts().size() == 1) {
                // 单个不可再分的单元比块还长（小 chunk_size 下的连续中文）：
                // 再递归就是原地打转，带着超长交给 merge 去响亮地拒绝
                splits.add(new Split(part, found.sentence(), partSize));
            } else {
                splits.addAll(splitInto(part, effectiveChunkSize));
            }
        }
        return splits;
    }

    private record Splits(List<String> parts, boolean sentence) {}

    /** 先按"整句"那两级切；切不开再降到子句/空格/单字，此时不再算完整句子。 */
    private Splits getSplitsByFns(String text) {
        for (Function<String, List<String>> fn : splitFns) {
            List<String> parts = fn.apply(text);
            if (parts.size() > 1) {
                return new Splits(parts, true);
            }
        }
        List<String> parts = List.of(text);
        for (Function<String, List<String>> fn : subSentenceSplitFns) {
            parts = fn.apply(text);
            if (parts.size() > 1) {
                break;
            }
        }
        return new Splits(parts, false);
    }

    /** 贪心装箱：装得下就续着装，装不下就封块，封块时把上一块尾部若干句按 overlap 挪进新块。 */
    private List<String> merge(List<Split> splits, int effectiveChunkSize) {
        List<String> chunks = new ArrayList<>();
        List<Split> current = new ArrayList<>();
        int currentLength = 0;
        boolean newChunk = true;

        int index = 0;
        while (index < splits.size()) {
            Split split = splits.get(index);
            if (split.tokenSize() > effectiveChunkSize) {
                throw new IllegalArgumentException("单片长度超过 chunk_size: " + split.tokenSize());
            }
            if (currentLength + split.tokenSize() > effectiveChunkSize && !newChunk) {
                // 加进来就爆块：先封当前块
                currentLength = closeChunk(chunks, current);
                newChunk = true;
            } else {
                if (newChunk && currentLength + split.tokenSize() > effectiveChunkSize) {
                    // 新块带着 overlap 还塞不下：从头部把 overlap 剔掉腾地方
                    while (!current.isEmpty() && currentLength + split.tokenSize() > effectiveChunkSize) {
                        currentLength -= current.removeFirst().tokenSize();
                    }
                }
                if (split.sentence() || currentLength + split.tokenSize() <= effectiveChunkSize || newChunk) {
                    currentLength += split.tokenSize();
                    current.add(split);
                    index++;
                    newChunk = false;
                } else {
                    currentLength = closeChunk(chunks, current);
                    newChunk = true;
                }
            }
        }
        if (!newChunk) {
            chunks.add(join(current));
        }
        return chunks;
    }

    /**
     * 封当前块，并从它尾部按 overlap 往新块里回填几句，返回新块的当前长度。
     *
     * 先抄一份再清：回填读的是刚封掉那块的原样（不能边清边读）
     * 天然分开了两个列表，这里共享同一个 List，不清醒一点就会把刚封的块读成空。
     */
    private int closeChunk(List<String> chunks, List<Split> current) {
        List<Split> closed = List.copyOf(current);
        chunks.add(join(closed));
        current.clear();
        int length = 0;
        // 从尾部往前攒，攒到正好不超过 overlap 为止
        for (int i = closed.size() - 1; i >= 0 && length + closed.get(i).tokenSize() <= chunkOverlap; i--) {
            length += closed.get(i).tokenSize();
            current.add(0, closed.get(i));
        }
        return length;
    }

    private static List<String> postprocess(List<String> chunks) {
        List<String> kept = new ArrayList<>();
        for (String chunk : chunks) {
            String stripped = chunk.strip();
            if (!stripped.isEmpty()) {
                kept.add(stripped);
            }
        }
        return kept;
    }

    /** 一个码点一个 token：中文一字一 token，chunk_size 就是字符数。 */
    private static int tokenSize(String text) {
        return text.codePointCount(0, text.length());
    }

    private static String join(List<Split> splits) {
        StringBuilder text = new StringBuilder();
        splits.forEach(split -> text.append(split.text()));
        return text.toString();
    }

    private static List<String> splitSentences(String text) {
        List<String> kept = new ArrayList<>();
        for (String part : SENTENCE.split(text, -1)) {
            if (!part.isBlank()) {
                kept.add(part);
            }
        }
        return kept;
    }

    /** re.findall：按模式逐个匹配取回，非全局匹配的空白片段也原样保留。 */
    private static List<String> findAll(Pattern pattern, String text) {
        List<String> found = new ArrayList<>();
        Matcher matcher = pattern.matcher(text);
        while (matcher.find()) {
            found.add(matcher.group());
        }
        return found;
    }

    private static List<String> splitByChar(String text) {
        List<String> chars = new ArrayList<>();
        text.codePoints().forEach(codePoint -> chars.add(new String(Character.toChars(codePoint))));
        return chars;
    }

    /** 按分隔符切开并把分隔符留在前一段末尾。 */
    private static Function<String, List<String>> splitBySeparatorKeeping(String separator) {
        return text -> {
            String[] parts = text.split(java.util.regex.Pattern.quote(separator), -1);
            List<String> result = new ArrayList<>();
            for (int i = 0; i < parts.length; i++) {
                String part = i == 0 ? parts[i] : separator + parts[i];
                if (!part.isEmpty()) {
                    result.add(part);
                }
            }
            return result;
        };
    }
}
