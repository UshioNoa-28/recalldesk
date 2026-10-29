package com.recalldesk.infrastructure.model;

import com.recalldesk.domain.port.model.QueryRewriter;
import com.recalldesk.domain.retrieval.QueryRewrite;
import org.springframework.stereotype.Component;

/**
 * 查询改写端口实现：prompt、JSON 清洗与空白兜底都在网关（Python）侧。
 *
 * 这里只做 JSON → 值对象的形状转换；queries 为空会在 record 构造期抛出，
 * 等于把网关照约定不该发出的坏响应变成显式失败。
 */
@Component
public class HttpQueryRewriter implements QueryRewriter {

    private final ModelServiceClient client;

    public HttpQueryRewriter(ModelServiceClient client) {
        this.client = client;
    }

    @Override
    public QueryRewrite rewrite(String query) {
        ModelServiceClient.RewriteResponse response = client.rewrite(query);
        return new QueryRewrite(response.queries(), response.keywords());
    }
}
