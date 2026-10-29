package com.recalldesk.infrastructure.persistence.mapper;

import com.recalldesk.infrastructure.persistence.row.EvalRunItemRow;
import com.recalldesk.infrastructure.persistence.row.RunCountRow;
import java.util.List;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/** eval_run_items 表：结果行的读写。jsonb 两列显式 CAST，所以不挂 BaseMapper。 */
@Mapper
public interface EvalRunItemMapper {

    @Insert("INSERT INTO eval_run_items (id, run_id, testset_item_id, hit_rank, latency_ms, "
            + "evidence_total, evidence_matched, evidence_ranks_json, channels_json) "
            + "VALUES (#{id}, #{runId}, #{testsetItemId}, #{hitRank}, #{latencyMs}, "
            + "#{evidenceTotal}, #{evidenceMatched}, "
            + "CAST(#{evidenceRanksJson, jdbcType=VARCHAR} AS jsonb), CAST(#{channelsJson, jdbcType=VARCHAR} AS jsonb))")
    int insert(EvalRunItemRow row);

    /**
     * 逐题结果，题面从 eval_testset_items 联查带出（inner join：题被级联删则结果一起消失）。
     *
     * 列名逐个点出来：两张表都有 id / status / created_at，SELECT r.* , q.* 的别名会撞车。
     */
    @Select("SELECT r.id, r.run_id, r.testset_item_id, r.hit_rank, r.latency_ms, r.evidence_total, "
            + "r.evidence_matched, r.evidence_ranks_json::text AS evidence_ranks_json, "
            + "r.channels_json::text AS channels_json, q.query "
            + "FROM eval_run_items r JOIN eval_testset_items q ON q.id = r.testset_item_id "
            + "WHERE r.run_id = #{runId} ORDER BY r.testset_item_id")
    List<EvalRunItemRow> listByRun(@Param("runId") String runId);

    /** 各 run 已写出几题结果：一次分组查询，列表页不给每行查一次。 */
    @Select("<script>SELECT run_id, COUNT(*) AS total FROM eval_run_items WHERE run_id IN "
            + "<foreach collection='runIds' item='id' open='(' separator=',' close=')'>#{id}</foreach>"
            + " GROUP BY run_id</script>")
    List<RunCountRow> countByRun(@Param("runIds") List<String> runIds);

    @Select("SELECT COUNT(*) FROM eval_run_items WHERE run_id = #{runId} AND testset_item_id = #{testsetItemId}")
    int countResult(@Param("runId") String runId, @Param("testsetItemId") String testsetItemId);
}
