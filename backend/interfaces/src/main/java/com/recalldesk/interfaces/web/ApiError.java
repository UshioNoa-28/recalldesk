package com.recalldesk.interfaces.web;

/**
 * 一条 HTTP 错误：状态码 + {@code detail} 原样的内容。
 *
 * FastAPI 的 HTTPException 就是这个形状——响应体永远只有 {@code {"detail": ...}}，
 * 而且 detail 既可以是字符串（404/400/409），也可以是 pydantic 的校验明细数组（422）。差异留在抛出处（各路由/advice），
 * 不再让调用方拼响应体。
 */
public class ApiError extends RuntimeException {

    private final int status;
    private final Object detail;

    public ApiError(int status, Object detail) {
        super(detail instanceof String text ? text : String.valueOf(detail));
        this.status = status;
        this.detail = detail;
    }

    public int status() {
        return status;
    }

    public Object detail() {
        return detail;
    }
}
