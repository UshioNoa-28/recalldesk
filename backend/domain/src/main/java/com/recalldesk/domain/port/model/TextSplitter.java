package com.recalldesk.domain.port.model;

import java.util.List;

/**
 * 把长文本切成 chunk 列表的能力（具体分块策略由实现决定）。
 *
 * 返回按原文顺序排列的非空 chunk。
 */
public interface TextSplitter {

    List<String> split(String text);
}
