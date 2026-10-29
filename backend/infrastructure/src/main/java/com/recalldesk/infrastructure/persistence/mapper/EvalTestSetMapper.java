package com.recalldesk.infrastructure.persistence.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.recalldesk.infrastructure.persistence.row.EvalTestSetRow;
import com.recalldesk.infrastructure.persistence.row.TestSetItemCountRow;
import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface EvalTestSetMapper extends BaseMapper<EvalTestSetRow> {

    @Select("SELECT * FROM eval_testsets WHERE user_id = #{userId} ORDER BY created_at DESC")
    List<EvalTestSetRow> listByUser(@Param("userId") String userId);

    /**
     * 一批测试集各自的题目数，LEFT JOIN 保空集：没有 GROUP BY 过滤掉 0 题的那些。
     *
     * user_id 也进 WHERE：调用方传的是自己名下的 id 集合，多这一道是防「拿着别人的 id
     * 拼进 IN 列表来探对方的题量」——隔离条件不该依赖上一层忘了漏。
     */
    @Select("<script>SELECT t.id AS testset_id, COUNT(i.id) AS total FROM eval_testsets t "
            + "LEFT JOIN eval_testset_items i ON i.testset_id = t.id "
            + "WHERE t.user_id = #{userId} AND t.id IN "
            + "<foreach collection='testSetIds' item='id' open='(' separator=',' close=')'>#{id}</foreach>"
            + " GROUP BY t.id</script>")
    List<TestSetItemCountRow> countItems(@Param("userId") String userId,
            @Param("testSetIds") List<String> testSetIds);
}
