package com.recalldesk.infrastructure.text;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 分块结果对拍：预期值来自 llama-index SentenceSplitter 的实跑，不是手算。
 *
 * 切法决定召回的粒度，历史评测 run 的可比性也压在这里——"看起来合理"的自写分块
 * 通不过这一关，因为它必然在长句、overlap、不可分片段这几处走出不同的边界。
 * fixture 一次性生成后落进 test resources，离线可跑。
 */
class SentenceTextSplitterTest {

    private record Case(String name, String text, int chunkSize, int chunkOverlap, List<String> chunks) {}

    private static final ObjectMapper MAPPER = new ObjectMapper()
            .setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

    private static List<Case> goldenCases() throws IOException {
        try (InputStream fixture = SentenceTextSplitterTest.class.getResourceAsStream("/text/split_golden.json")) {
            if (fixture == null) {
                throw new IllegalStateException("缺 fixture：/text/split_golden.json");
            }
            return MAPPER.readValue(
                    fixture, MAPPER.getTypeFactory().constructCollectionType(List.class, Case.class));
        }
    }

    @Test
    @DisplayName("13 种文本 × 6 档 chunk_size/overlap：逐块逐字相等")
    void matchesSentenceSplitterGolden() throws IOException {
        for (Case testCase : goldenCases()) {
            List<String> chunks =
                    new SentenceTextSplitter(testCase.chunkSize(), testCase.chunkOverlap()).split(testCase.text());
            assertThat(chunks)
                    .as("%s @ chunk_size=%d chunk_overlap=%d",
                            testCase.name(), testCase.chunkSize(), testCase.chunkOverlap())
                    .isEqualTo(testCase.chunks());
        }
    }

    @Test
    @DisplayName("overlap 逐块挪进下一块：长句连续时块与块首尾相接")
    void overlapCarriesTailSentences() throws IOException {
        Case mixedPunct = goldenCases().stream()
                .filter(item -> item.name().equals("mixed_punct") && item.chunkSize() == 20
                        && item.chunkOverlap() == 20)
                .findFirst()
                .orElseThrow();

        assertThat(mixedPunct.chunks()).hasSize(4);
        // overlap=chunk_size 时前一块整块挪进下一块开头，块与块首尾相接
        assertThat(mixedPunct.chunks().get(2)).startsWith("它支持图像输入吗？");
    }

    @Test
    @DisplayName("配置自相矛盾时在构造期就拒绝，不等第一份文档")
    void invalidConfigurationRejected() {
        assertThatThrownBy(() -> new SentenceTextSplitter(10, 11))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("chunk_overlap");
        assertThatThrownBy(() -> new SentenceTextSplitter(0, 0))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("chunk_size");
    }
}
