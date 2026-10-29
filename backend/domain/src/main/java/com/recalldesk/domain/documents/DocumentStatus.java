package com.recalldesk.domain.documents;

public enum DocumentStatus {
    PENDING("pending"),
    SUCCESS("success"),
    FAILED("failed");

    private final String wire;

    DocumentStatus(String wire) {
        this.wire = wire;
    }

    public String wire() {
        return wire;
    }

    public static DocumentStatus from(String value) {
        for (DocumentStatus status : values()) {
            if (status.wire.equals(value)) {
                return status;
            }
        }
        throw new IllegalArgumentException("未知文档状态: " + value);
    }
}
