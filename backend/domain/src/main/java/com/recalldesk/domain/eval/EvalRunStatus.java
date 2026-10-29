package com.recalldesk.domain.eval;

/** 一次评测运行的生命周期。 */
public enum EvalRunStatus {
    RUNNING("running"),
    DONE("done"),
    FAILED("failed");

    private final String wire;

    EvalRunStatus(String wire) {
        this.wire = wire;
    }

    public String wire() {
        return wire;
    }

    public static EvalRunStatus from(String value) {
        for (EvalRunStatus status : values()) {
            if (status.wire.equals(value)) {
                return status;
            }
        }
        throw new IllegalArgumentException("未知运行状态: " + value);
    }
}
