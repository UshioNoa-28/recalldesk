package com.recalldesk.domain.documents;

/** 任务投递与执行的生命周期（Transactional Outbox 的行状态）。 */
public enum DocumentTaskStatus {
    PENDING("pending"),
    QUEUE("queue"),
    SUCCESS("success"),
    FAILED("failed");

    private final String wire;

    DocumentTaskStatus(String wire) {
        this.wire = wire;
    }

    public String wire() {
        return wire;
    }

    public static DocumentTaskStatus from(String value) {
        for (DocumentTaskStatus status : values()) {
            if (status.wire.equals(value)) {
                return status;
            }
        }
        throw new IllegalArgumentException("未知任务状态: " + value);
    }
}
