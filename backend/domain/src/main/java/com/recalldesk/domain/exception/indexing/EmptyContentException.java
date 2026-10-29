package com.recalldesk.domain.exception.indexing;

/** 文档切不出任何分块：内容本身的问题，重试不会变好。 */
public class EmptyContentException extends RuntimeException {

    public EmptyContentException(String message) {
        super(message);
    }
}
