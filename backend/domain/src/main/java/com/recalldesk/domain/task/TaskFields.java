package com.recalldesk.domain.task;

/** 消息字段的判定口径：各条链路提取任务 ID 时用的是同一套"假值"语义。 */
public final class TaskFields {

    private TaskFields() {}

    /** null 与空串算缺，纯空白是合法值。 */
    public static boolean missing(String value) {
        return value == null || value.isEmpty();
    }
}
