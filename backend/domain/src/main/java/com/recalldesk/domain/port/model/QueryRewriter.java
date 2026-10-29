package com.recalldesk.domain.port.model;

import com.recalldesk.domain.retrieval.QueryRewrite;

/** 查询改写端口：模型侧怎么调不进领域，这里只认"原始查询进、变体与关键词出"。 */
public interface QueryRewriter {

    QueryRewrite rewrite(String query);
}
