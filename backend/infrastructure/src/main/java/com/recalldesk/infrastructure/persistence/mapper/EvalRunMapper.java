package com.recalldesk.infrastructure.persistence.mapper;

import com.recalldesk.infrastructure.persistence.row.EvalRunRow;
import java.util.List;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/** eval_runs 表：两个 jsonb 列必须显式 CAST，所以整表走手写 SQL，不挂 BaseMapper。 */
@Mapper
public interface EvalRunMapper {

    @Insert("INSERT INTO eval_runs (id, user_id, testset_id, status, config_json, metrics_json, error_message, "
            + "created_at, finished_at) VALUES (#{id}, #{userId}, #{testsetId}, #{status}, "
            + "CAST(#{configJson, jdbcType=VARCHAR} AS jsonb), CAST(#{metricsJson, jdbcType=VARCHAR} AS jsonb), "
            + "#{errorMessage}, now(), NULL)")
    int insert(EvalRunRow row);

    @Select("SELECT id, user_id, testset_id, status, config_json::text AS config_json, "
            + "metrics_json::text AS metrics_json, error_message, created_at, finished_at "
            + "FROM eval_runs WHERE id = #{id}")
    EvalRunRow selectById(@Param("id") String id);

    @Select("SELECT id, user_id, testset_id, status, config_json::text AS config_json, "
            + "metrics_json::text AS metrics_json, error_message, created_at, finished_at "
            + "FROM eval_runs WHERE user_id = #{userId} AND testset_id = #{testsetId} "
            + "ORDER BY created_at DESC")
    List<EvalRunRow> listByTestset(@Param("userId") String userId, @Param("testsetId") String testsetId);

    /**
     * 收尾的条件写：WHERE 里钉住 status='running'，重复调用与启动扫相撞都匹配不到行，
     * finished_at 因此只会有第一次那个值。
     */
    @Update("UPDATE eval_runs SET status = #{status}, "
            + "metrics_json = CAST(#{metricsJson, jdbcType=VARCHAR} AS jsonb), error_message = #{errorMessage}, "
            + "finished_at = now() WHERE id = #{id} AND status = 'running'")
    int finishIfRunning(@Param("id") String id, @Param("status") String status,
            @Param("metricsJson") String metricsJson, @Param("errorMessage") String errorMessage);

    /** 只有 failed 能重开：已 running / 已 done 都是空操作。 */
    @Update("UPDATE eval_runs SET status = 'running', error_message = NULL, finished_at = NULL "
            + "WHERE id = #{id} AND status = 'failed'")
    int reopen(@Param("id") String id);

    /**
     * 删掉包含「以该文档为出处」的题目的 run，返回删除数。
     *
     * 从 run_tasks 反查而不是 run_items：题还没跑完时只有任务行，没有结果行。
     * run_items / run_tasks 随 run 级联删除。
     */
    @Delete("DELETE FROM eval_runs WHERE id IN ("
            + "SELECT DISTINCT t.run_id FROM eval_run_tasks t "
            + "WHERE t.item_id IN (SELECT e.item_id FROM eval_testset_item_evidence e "
            + "WHERE e.document_id = #{documentId}))")
    int deleteReferencingDocument(@Param("documentId") String documentId);
}
