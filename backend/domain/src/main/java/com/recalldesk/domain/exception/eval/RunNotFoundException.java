package com.recalldesk.domain.exception.eval;

/** 评测运行不存在。 */
public class RunNotFoundException extends RuntimeException {

    public RunNotFoundException(String runId) {
        super("评测运行不存在: " + runId);
    }
}
