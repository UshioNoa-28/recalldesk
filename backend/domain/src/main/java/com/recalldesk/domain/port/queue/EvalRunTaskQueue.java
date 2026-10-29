package com.recalldesk.domain.port.queue;

/**
 * Eval 逐题评测任务队列（anna_rag_eval_run_tasks）。
 *
 * 消息带 runId + itemId：消费者手上只有坐标，题目与 run 配置现查。
 */
public interface EvalRunTaskQueue extends StreamQueue {

    /** 发布一条逐题评测任务，返回消息 ID。 */
    String enqueue(String taskId, String runId, String itemId);
}
