package com.recalldesk.interfaces.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.recalldesk.application.auth.EmailCodeService;
import com.recalldesk.domain.port.auth.EmailCodeStore;
import com.recalldesk.domain.port.auth.EmailSender;
import com.recalldesk.domain.port.auth.TokenGateway;
import com.recalldesk.infrastructure.mail.SmtpEmailSender;
import com.recalldesk.infrastructure.redis.RedisEmailCodeStore;
import com.recalldesk.infrastructure.security.JjwtTokenGateway;
import com.recalldesk.interfaces.security.AuthenticatedUserMvcConfigurer;
import com.recalldesk.interfaces.security.JwtAuthFilter;
import java.time.Duration;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.Ordered;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.mail.MailSender;

/**
 * 鉴权接线：谁能不带令牌进来、令牌多久过期、验过之后身份怎么进控制器。
 *
 * 这里是整个系统唯一读 JWT 配置的地方（密钥、TTL、白名单），适配器与业务都不碰
 * {@code @Value}——与 {@link SearchConfiguration} 同一个规矩。
 *
 * 白名单写成配置项而不是硬编码在过滤器里：将来加探针或回调路径时，改的是那段
 * 「哪些接口不带身份」的清单，而不是过滤器代码。
 *
 * 身份进控制器参数那一步在 {@link AuthenticatedUserMvcConfigurer}，不在这儿：切片测试要的是
 * 解析器，不是这套配置。
 */
@Configuration(proxyBeanMethods = false)
public class AuthConfiguration {

    /**
     * 令牌适配器：登出吊销的键就存在 Redis，TTL 取 refresh 的最长寿命——键活过所有
     * 「早于吊销时间点签发」的令牌之后自动消失，不需要清理任务。
     */
    @Bean
    public TokenGateway tokenGateway(
            @Value("${recalldesk.jwt.secret}") String secret,
            @Value("${recalldesk.jwt.access-ttl}") Duration accessTtl,
            @Value("${recalldesk.jwt.refresh-ttl}") Duration refreshTtl,
            StringRedisTemplate redis) {
        return new JjwtTokenGateway(secret, accessTtl, refreshTtl, redis);
    }

    @Bean
    public EmailCodeStore emailCodeStore(StringRedisTemplate redis) {
        return new RedisEmailCodeStore(redis);
    }

    /**
     * 验证码发信：SMTP 连接由 Spring Boot 的 {@code spring.mail.*} 装配好，
     * 这里只把发件人地址递给适配器。口令（授权码）只在配置里出现，永不进代码与日志。
     *
     * 发件人为空时启动即失败：空 From 只会在用户点「发送验证码」时才炸成 500
     * （jakarta.mail 的 Illegal address），那是把配置错误推给用户去踩。
     */
    @Bean
    public EmailSender emailSender(MailSender mailSender, @Value("${recalldesk.auth.mail-from:}") String from) {
        if (from == null || from.isBlank()) {
            throw new IllegalStateException(
                    "MAIL_FROM 未配置：验证码邮件需要一个发件地址（QQ 邮箱要求与 SMTP_USERNAME 一致）");
        }
        return new SmtpEmailSender(mailSender, from.trim());
    }

    @Bean
    public EmailCodeService emailCodeService(
            EmailCodeStore store, EmailSender sender, @Value("${recalldesk.auth.email-code-ttl}") Duration ttl) {
        return new EmailCodeService(store, sender, ttl);
    }

    @Bean
    public FilterRegistrationBean<JwtAuthFilter> jwtAuthFilter(
            TokenGateway tokenGateway,
            ObjectMapper objectMapper,
            @Value("${recalldesk.jwt.public-paths}") List<String> publicPaths) {
        FilterRegistrationBean<JwtAuthFilter> registration =
                new FilterRegistrationBean<>(new JwtAuthFilter(tokenGateway, publicPaths, objectMapper));
        registration.setUrlPatterns(List.of("/*"));
        registration.setOrder(Ordered.HIGHEST_PRECEDENCE + 10);
        return registration;
    }
}
