package com.recalldesk.infrastructure.persistence.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.recalldesk.infrastructure.persistence.row.DocumentRow;
import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface DocumentMapper extends BaseMapper<DocumentRow> {

    /** 分页：某用户的文档，创建时间倒序（隔离谓词在 SQL 里，不是取回后筛）。 */
    @Select("SELECT * FROM documents WHERE user_id = #{userId} "
            + "ORDER BY created_at DESC LIMIT #{limit} OFFSET #{offset}")
    List<DocumentRow> listPageOwned(
            @Param("userId") String userId, @Param("limit") int limit, @Param("offset") long offset);

    /** 分页 total：某用户名下有多少篇。 */
    @Select("SELECT count(*) FROM documents WHERE user_id = #{userId}")
    long countOwned(@Param("userId") String userId);
}
