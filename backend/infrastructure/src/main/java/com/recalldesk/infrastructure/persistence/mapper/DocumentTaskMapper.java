package com.recalldesk.infrastructure.persistence.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.recalldesk.infrastructure.persistence.row.DocumentTaskRow;
import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface DocumentTaskMapper extends BaseMapper<DocumentTaskRow> {

    /**
     * 出箱取行：到期的 PENDING + FOR UPDATE SKIP LOCKED。
     *
     * 到期判定用库的 now() 而不是应用时钟——多副本各自对表没意义，同一颗钟还省掉时钟漂移。
     * ORDER BY created_at, id 是必须的：SKIP LOCKED 跳过被别人锁住的行后，靠 id 保证全序。
     */
    @Select("SELECT * FROM document_tasks "
            + "WHERE status = 'pending' AND (next_retry_at IS NULL OR next_retry_at <= now()) "
            + "ORDER BY created_at, id LIMIT #{limit} FOR UPDATE SKIP LOCKED")
    List<DocumentTaskRow> listPendingForUpdate(@Param("limit") int limit);

    @Update("UPDATE document_tasks SET status = 'queue', queued_at = now(), last_error = NULL WHERE id = #{id}")
    int markQueued(@Param("id") String id);

    @Update("UPDATE document_tasks SET status = 'success' WHERE id = #{id}")
    int markSuccess(@Param("id") String id);

    @Update("UPDATE document_tasks SET status = 'failed' WHERE id = #{id}")
    int markFailed(@Param("id") String id);

    /**
     * 记一次失败：attempts+1、回到 pending、下次重试时间按 base * 2^attempts 指数退避。
     *
     * 幂写在一条 SQL 里（读行改字段再写回是两次 SQL，并发下会丢一次自增）：
     * 退避用的正是自增前的 attempts，即 2^(attempts-1)。
     */
    @Update("UPDATE document_tasks SET attempts = attempts + 1, status = 'pending', last_error = #{error}, "
            + "next_retry_at = now() + make_interval(secs => (#{baseSeconds} * power(2, attempts))::int) "
            + "WHERE id = #{id}")
    int recordFailure(@Param("id") String id, @Param("error") String error,
            @Param("baseSeconds") double baseSeconds);
}
