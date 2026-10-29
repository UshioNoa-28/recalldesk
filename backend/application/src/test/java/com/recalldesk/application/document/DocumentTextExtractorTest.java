package com.recalldesk.application.document;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class DocumentTextExtractorTest {

    private static final String BOM = String.valueOf((char) 0xFEFF);
    private static final String IDEOGRAPHIC_SPACE = String.valueOf((char) 0x3000);
    private static final String NBSP = String.valueOf((char) 0x00A0);

    private static byte[] utf8(String text) {
        return text.getBytes(StandardCharsets.UTF_8);
    }

    @Test
    @DisplayName("只剥开头 BOM，正文逐字保留（字符卫生层已随 txt/md 单一入口退役）")
    void stripsLeadingBomAndKeepsTextVerbatim() {
        // 全角空格、NBSP、组合重音一律原样入库，比对时的折叠归 TextNormalizer 管
        String raw = BOM + "标题" + IDEOGRAPHIC_SPACE + NBSP + "é";

        assertThat(DocumentTextExtractor.extract(utf8(raw)))
                .isEqualTo("标题" + IDEOGRAPHIC_SPACE + NBSP + "é");
        // 正文中间的 BOM 属于内容，不是编码标记
        assertThat(DocumentTextExtractor.extract(utf8("a" + BOM + "b"))).isEqualTo("a" + BOM + "b");
    }

    @Test
    @DisplayName("非法 UTF-8 字节响亮拒绝，不替换成 U+FFFD 混进索引")
    void rejectsInvalidUtf8() {
        byte[] broken = new byte[] {'a', (byte) 0xC3, (byte) 0x28};

        assertThatThrownBy(() -> DocumentTextExtractor.extract(broken))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("UTF-8");
    }

    @Test
    @DisplayName("只有空白的文件算空文件")
    void rejectsBlankContent() {
        assertThatThrownBy(() -> DocumentTextExtractor.extract(utf8("  \n\t ")))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("文件内容为空");
        assertThatThrownBy(() -> DocumentTextExtractor.extract(new byte[0]))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("文件内容为空");
    }

    @Test
    @DisplayName("全 BOM 的文件剥完就是空文件")
    void rejectsBomOnlyContent() {
        assertThatThrownBy(() -> DocumentTextExtractor.extract(utf8(BOM)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("文件内容为空");
    }
}
