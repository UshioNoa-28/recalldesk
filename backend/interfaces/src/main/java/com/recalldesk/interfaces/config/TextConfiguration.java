package com.recalldesk.interfaces.config;

import com.recalldesk.domain.port.model.TextSplitter;
import com.recalldesk.infrastructure.text.SentenceTextSplitter;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 分块器的接线：块长与重叠从配置读一次，实现类自己不碰 {@code @Value}。
 *
 * 两个数的语义：一个码点算一个 token，所以 chunk-size 就是字符数（中文一字一 token）；
 * chunk-overlap 决定相邻块共享多少字符。改这两个值等于改分块口径，历史 run 的
 * 召回结果不再可比——它们是「检索配方」的一部分，不是随手可调的运维参数。
 */
@Configuration(proxyBeanMethods = false)
public class TextConfiguration {

    @Bean
    public TextSplitter textSplitter(
            @Value("${recalldesk.chunk-size:512}") int chunkSize,
            @Value("${recalldesk.chunk-overlap:64}") int chunkOverlap) {
        return new SentenceTextSplitter(chunkSize, chunkOverlap);
    }
}
