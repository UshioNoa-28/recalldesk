package com.recalldesk.application.eval.dto;

import com.recalldesk.application.eval.EvalMetrics;
import com.recalldesk.domain.eval.ChannelScore;
import com.recalldesk.domain.eval.EvalRunItem;
import java.util.List;

/** 逐题结果的 DTO：原始结果 + 现算的指标。 */
public record EvalRunItemDto(
        String testsetItemId,
        String query,
        Integer hitRank,
        List<Integer> evidenceRanks,
        int recall,
        double map,
        double latencyMs,
        int evidenceTotal,
        int evidenceMatched,
        double evidenceCoverage,
        List<ChannelView> channels) {

    public record ChannelView(String kind, String text, List<Integer> ranks, int recall, double map,
            int evidenceMatched, Long tookMs) {}

    public static EvalRunItemDto of(EvalRunItem item) {
        return new EvalRunItemDto(
                item.testsetItemId(),
                item.query(),
                item.hitRank(),
                item.evidenceRanks(),
                EvalMetrics.jointHit(item),
                EvalMetrics.averagePrecision(item),
                item.latencyMs(),
                item.evidenceTotal(),
                item.evidenceMatched(),
                EvalMetrics.evidenceCoverage(item),
                item.channels().stream().map(channel -> channelView(item, channel)).toList());
    }

    private static ChannelView channelView(EvalRunItem item, ChannelScore channel) {
        EvalRunItem derived = EvalMetrics.asChannel(item, channel);
        return new ChannelView(
                channel.kind(),
                channel.text(),
                channel.ranks(),
                EvalMetrics.jointHit(derived),
                EvalMetrics.averagePrecision(derived),
                derived.evidenceMatched(),
                channel.tookMs());
    }

}
