package com.recalldesk.infrastructure.persistence.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.recalldesk.infrastructure.persistence.row.EvalRunTaskRow;
import com.recalldesk.infrastructure.persistence.row.StatusCountRow;
import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/** 逐题评测任务发件箱。语句与 EvalTaskMapper 同形（表名不同），一表一份。 */
@Mapper
public interface EvalRunTaskMapper extends BaseMapper<EvalRunTaskRow> {

    /**
     * 出箱取行：到期的 PENDING + FOR UPDATE SKIP LOCKED。
     *
     * 到期判定用库的 now() 而不是应用时钟；ORDER BY created_at, id 保证全序，
     * 跳过被锁行之后不会漏也不会重。
     */
    @Select("SELECT * FROM eval_run_tasks "
            + "WHERE status = 'pending' AND (next_retry_at IS NULL OR next_retry_at <= now()) "
            + "ORDER BY created_at, id LIMIT #{limit} FOR UPDATE SKIP LOCKED")
    List<EvalRunTaskRow> listPendingForUpdate(@Param("limit") int limit);

    @Update("UPDATE eval_run_tasks SET status = 'queue', queued_at = now(), last_error = NULL WHERE id = #{id}")
    int markQueued(@Param("id") String id);

    @Update("UPDATE eval_run_tasks SET status = 'success' WHERE id = #{id}")
    int markSuccess(@Param("id") String id);

    @Update("UPDATE eval_run_tasks SET status = 'failed' WHERE id = #{id}")
    int markFailed(@Param("id") String id);

    /** 记一次失败：attempts+1、回到 pending、下次重试时间按 base * 2^attempts 指数退避。 */
    @Update("UPDATE eval_run_tasks SET attempts = attempts + 1, status = 'pending', last_error = #{error}, "
            + "next_retry_at = now() + make_interval(secs => (#{baseSeconds} * power(2, attempts))::int) "
            + "WHERE id = #{id}")
    int recordFailure(@Param("id") String id, @Param("error") String error,
            @Param("baseSeconds") double baseSeconds);

    /**
     * 整 run 复位：把终态 FAILED 的任务翻回 pending，返回条数（0 也是合法结果，不炸）。
     *
     * 与出题侧的 resetForRetry 不同——那条按 item_id 复位单行、没命中就抛，
     * 这条是"重跑整个 run"的批量前置。
     */
    @Update("UPDATE eval_run_tasks SET status = 'pending', attempts = 0, last_error = NULL, "
            + "next_retry_at = NULL WHERE run_id = #{runId} AND status = 'failed'")
    int resetFailedForRun(@Param("runId") String runId);

    @Select("SELECT status, COUNT(*) AS total FROM eval_run_tasks WHERE run_id = #{runId} GROUP BY status")
    List<StatusCountRow> countByStatus(@Param("runId") String runId);
}
