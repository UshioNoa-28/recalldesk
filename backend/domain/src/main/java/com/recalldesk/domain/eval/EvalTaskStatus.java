package com.recalldesk.domain.eval;

/** 逐题任务的发件箱状态。 */
public enum EvalTaskStatus {
    PENDING("pending"),
    QUEUE("queue"),
    SUCCESS("success"),
    FAILED("failed");

    private final String wire;

    EvalTaskStatus(String wire) {
        this.wire = wire;
    }

    public String wire() {
        return wire;
    }

    public static EvalTaskStatus from(String value) {
        for (EvalTaskStatus status : values()) {
            if (status.wire.equals(value)) {
                return status;
            }
        }
        throw new IllegalArgumentException("未知任务状态: " + value);
    }
}
