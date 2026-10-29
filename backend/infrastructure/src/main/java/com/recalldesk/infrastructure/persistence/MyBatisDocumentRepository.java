package com.recalldesk.infrastructure.persistence;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.recalldesk.domain.Page;
import com.recalldesk.domain.documents.Document;
import com.recalldesk.domain.port.persistence.DocumentRepository;
import com.recalldesk.infrastructure.persistence.mapper.DocumentMapper;
import com.recalldesk.infrastructure.persistence.row.DocumentRow;
import java.util.List;
import java.util.NoSuchElementException;
import java.util.Optional;
import org.springframework.stereotype.Repository;

/**
 * documents 表的 MyBatis-Plus 实现。
 *
 * 面向调用方的读与删除都带 user_id 谓词：跨用户的行在 SQL 层就看不见，
 * 于是「越权」与「不存在」得到同一个答案，应用层没有第二条分支可写错。
 */
@Repository
public class MyBatisDocumentRepository implements DocumentRepository {

    private final DocumentMapper mapper;

    public MyBatisDocumentRepository(DocumentMapper mapper) {
        this.mapper = mapper;
    }

    @Override
    public void add(Document document) {
        mapper.insert(DocumentRow.from(document));
    }

    @Override
    public Optional<Document> get(String documentId) {
        return Optional.ofNullable(mapper.selectById(documentId)).map(DocumentRow::toDomain);
    }

    @Override
    public Optional<Document> getOwned(String userId, String documentId) {
        return Optional.ofNullable(mapper.selectOne(
                        new QueryWrapper<DocumentRow>().eq("id", documentId).eq("user_id", userId), false))
                .map(DocumentRow::toDomain);
    }

    @Override
    public Page<Document> list(String userId, int page, int pageSize) {
        long total = mapper.countOwned(userId);
        List<Document> items =
                mapper.listPageOwned(userId, pageSize, (long) (page - 1) * pageSize).stream()
                        .map(DocumentRow::toDomain)
                        .toList();
        return new Page<>(items, total);
    }

    @Override
    public void update(Document document) {
        if (mapper.updateById(DocumentRow.from(document)) == 0) {
            // 文档不在了：抛领域异常，路由层按 404 处理
            throw new NoSuchElementException(document.id());
        }
    }

    @Override
    public boolean delete(String userId, String documentId) {
        return mapper.delete(new QueryWrapper<DocumentRow>().eq("id", documentId).eq("user_id", userId)) > 0;
    }

}
