package com.recalldesk.domain.exception.eval;

/** 评测集不存在。 */
public class TestSetNotFoundException extends RuntimeException {

    public TestSetNotFoundException(String testSetId) {
        super("评测集不存在: " + testSetId);
    }
}
