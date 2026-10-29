package com.recalldesk.domain.exception.documents;

/** 文档不存在。 */
public class DocumentNotFoundException extends RuntimeException {

    public DocumentNotFoundException(String documentId) {
        super("文档不存在: " + documentId);
    }
}
