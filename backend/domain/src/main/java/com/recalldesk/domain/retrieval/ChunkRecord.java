package com.recalldesk.domain.retrieval;

/** 原文回读的一个分块 */
public record ChunkRecord(
        String documentId, int chunkIndex, String text, String documentName, Integer chunkCount) {}
