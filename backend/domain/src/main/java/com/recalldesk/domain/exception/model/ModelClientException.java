package com.recalldesk.domain.exception.model;

/** 模型端点调不通：连不上、非 2xx、响应不是 JSON，或结构化输出两次都没解析出来。 */
public class ModelClientException extends RuntimeException {

    /** HTTP 状态码；-1 表示压根没拿到响应。 */
    private final int statusCode;

    public ModelClientException(int statusCode, String message, Throwable cause) {
        super(message, cause);
        this.statusCode = statusCode;
    }

    public ModelClientException(int statusCode, String message) {
        this(statusCode, message, null);
    }

    public int statusCode() {
        return statusCode;
    }

    /** 是否值得重试：5xx（服务端临时不行）才重试，4xx 重试只是浪费时间。 */
    public boolean retryable() {
        return statusCode >= 500;
    }
}
