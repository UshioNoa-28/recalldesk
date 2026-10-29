package com.recalldesk.application.worker;

/**
 * 失败原因的人话：{@code 类型名: 消息}——落库的 last_error 统一成这个形状，好按类型筛。
 *
 * 落进 last_error / documents.error_message 的那段文本是排障的唯一线索，
 * 五处（两个 publisher、三个 consumer）写法统一才筛得出来。
 */
final class TaskErrors {

    private TaskErrors() {}

    static String describe(Throwable error) {
        String message = error.getMessage();
        return error.getClass().getSimpleName() + ": " + (message == null ? "" : message);
    }
}
