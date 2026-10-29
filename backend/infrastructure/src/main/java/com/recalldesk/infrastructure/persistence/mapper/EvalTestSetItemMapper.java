package com.recalldesk.infrastructure.persistence.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.recalldesk.infrastructure.persistence.row.EvalTestSetItemRow;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface EvalTestSetItemMapper extends BaseMapper<EvalTestSetItemRow> {

    /**
     * 列表口径按 created_at 升序。
     *
     * 只排 created_at、不拿 id 兜底：now() 在一个事务里是常数，同批写入的题目 created_at
     * 完全相同，用 uuid 排会把写入顺序打乱成字典序——导入顺序就是用户在文件里的顺序，
     * 那正是他要能对照自己 jsonl 行号的东西。真要稳定还原写入顺序得给 items 加序号列，
     * 那属于"建表先不改"。
     */
    @Select("SELECT * FROM eval_testset_items WHERE testset_id = #{testsetId} ORDER BY created_at")
    List<EvalTestSetItemRow> listByTestSet(@Param("testsetId") String testsetId);

    /**
     * run 的分母：测试集当前的题数。
     *
     * 是「当前」而不是「开跑那一刻」——没有题级快照，所以 run 跑完之后再往集里加题，
     * 历史 run 的 total 会跟着涨。真要看某次跑了几题，metrics 里的 queries 才是那次的事实。
     */
    @Select("SELECT COUNT(*) FROM eval_testset_items WHERE testset_id = #{testsetId}")
    int countByTestSet(@Param("testsetId") String testsetId);

    /**
     * 删掉把该文档当证据的题目，返回删除数。
     *
     * 「文档消失 => 引用它的题消失」这条语义没有外键撑着（evidence→documents 是 RESTRICT，
     * 只会拦住不会代劳），完全靠这里显式维护；漏调的话删文档行会撞那道 RESTRICT。
     * 连带 eval_run_items 历史行随题目 CASCADE 一起走。
     */
    @Delete("DELETE FROM eval_testset_items WHERE id IN "
            + "(SELECT item_id FROM eval_testset_item_evidence WHERE document_id = #{documentId})")
    int deleteReferencingDocument(@Param("documentId") String documentId);
}
