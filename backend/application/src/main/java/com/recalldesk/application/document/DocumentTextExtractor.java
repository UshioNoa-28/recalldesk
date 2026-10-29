package com.recalldesk.application.document;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;

/**
 * 把上传的原始字节读成文本：严格 UTF-8 解码 → 剥 BOM → 全空白即拒。
 *
 * 只收 txt/md，PDF/HTML 的正文提取路线已整体退役，所以这里既没有按后缀分派那一层，
 * 也不做字符卫生（奇异空白、隐形字符、NFC 归一）——入库文本就是文件里的文本。
 *
 * 解码用 REPORT 而不是默认的替换字符：坏字节当垃圾读进来，会得到一堆 U+FFFD 并顺利
 * 入库，脏数据就是这么静默进索引的。
 */
public final class DocumentTextExtractor {

    private DocumentTextExtractor() {}

    public static String extract(byte[] content) {
        String decoded;
        try {
            decoded = StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(content))
                    .toString();
        } catch (CharacterCodingException e) {
            throw new IllegalArgumentException("文件不是合法的 UTF-8 文本: " + e.getMessage(), e);
        }
        // utf-8-sig 的语义：只有开头的 BOM 算编码标记，正文中间的 BOM 是内容
        String text = decoded.startsWith("\uFEFF") ? decoded.substring(1) : decoded;
        if (text.isBlank()) {
            throw new IllegalArgumentException("文件内容为空");
        }
        return text;
    }
}
