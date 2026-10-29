package com.recalldesk.application.document.dto;

/** 原始文件重读出来的文档（名字 + 文本）：磁盘上的原件才是权威，chunks 里的只是派生副本。 */
public record DocumentContent(String name, String text) {}
