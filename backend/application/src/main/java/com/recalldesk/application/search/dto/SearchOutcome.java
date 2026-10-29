package com.recalldesk.application.search.dto;

import com.recalldesk.domain.retrieval.ChannelTrace;
import com.recalldesk.domain.retrieval.ChunkHit;
import java.util.List;

/**
 * 检索的完整产出：对外结果 + 评估要用的每路轨迹。
 *
 * 只取对外结果的调用方读 {@link #hits()}；节点评估要的是 channels——各路检索完
 * 就被融合吃掉，轨迹不吐出来就丢了。
 */
public record SearchOutcome(List<ChunkHit> hits, List<ChannelTrace> channels) {

    public SearchOutcome {
        hits = List.copyOf(hits);
        channels = List.copyOf(channels);
    }
}
