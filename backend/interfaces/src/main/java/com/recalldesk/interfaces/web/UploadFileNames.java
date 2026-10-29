package com.recalldesk.interfaces.web;

import java.util.Locale;

/** 上传文件名的小工具：两个上传端点共用同一套后缀解析。 */
final class UploadFileNames {

    private UploadFileNames() {}

    /** PurePosixPath("a.b.md").suffix → ".md"（只看最后一段，大小写归一；隐藏文件不算后缀）。 */
    static String suffixOf(String filename) {
        int slash = filename.lastIndexOf('/');
        String base = slash >= 0 ? filename.substring(slash + 1) : filename;
        int dot = base.lastIndexOf('.');
        return dot <= 0 ? "" : base.substring(dot).toLowerCase(Locale.ROOT);
    }
}
