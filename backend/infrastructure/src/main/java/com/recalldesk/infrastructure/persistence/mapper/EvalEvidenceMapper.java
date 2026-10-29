package com.recalldesk.infrastructure.persistence.mapper;

import com.recalldesk.infrastructure.persistence.row.EvalEvidenceRow;
import java.util.List;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/** 金标子表：一个 (document, chunk) 一行，读写都是显式 SQL。 */
@Mapper
public interface EvalEvidenceMapper {

    @Insert("INSERT INTO eval_testset_item_evidence "
            + "(id, item_id, document_id, chunk_index, ordinal) "
            + "VALUES (#{id}, #{itemId}, #{documentId}, #{chunkIndex}, #{ordinal})")
    int insert(EvalEvidenceRow row);

    /** 一批题目的金标，按 (item_id, ordinal) 排：拼装顺序就是金标顺序。 */
    @Select("<script>SELECT id, item_id, document_id, chunk_index, ordinal "
            + "FROM eval_testset_item_evidence "
            + "WHERE item_id IN <foreach collection='itemIds' item='id' open='(' separator=',' close=')'>#{id}</foreach>"
            + " ORDER BY item_id, ordinal</script>")
    List<EvalEvidenceRow> listByItems(@Param("itemIds") List<String> itemIds);
}
