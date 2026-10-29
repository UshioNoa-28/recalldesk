package com.recalldesk.infrastructure.mail;

import com.recalldesk.domain.port.auth.EmailSender;
import org.springframework.mail.MailException;
import org.springframework.mail.MailSender;
import org.springframework.mail.SimpleMailMessage;

/**
 * 用 SMTP 发验证码邮件。
 *
 * 这里只拼一封信，主机/端口/TLS/账号全由 Spring Boot 的 {@code spring.mail.*} 注入到
 * {@link MailSender}（QQ 邮箱走 {@code smtp.qq.com:465} + SSL + 授权码当口令）。
 * 授权码是凭证：只从环境变量读，不进代码、不进日志、不进仓库。
 *
 * 发信失败原样抛出（不吞成 false）：没送到的码却告诉用户"已发送"，用户会白等十分钟。
 */
public class SmtpEmailSender implements EmailSender {

    private final MailSender mailSender;
    private final String from;

    public SmtpEmailSender(MailSender mailSender, String from) {
        this.mailSender = mailSender;
        this.from = from;
    }

    @Override
    public void sendVerificationCode(String email, String code, long validMinutes) {
        SimpleMailMessage message = new SimpleMailMessage();
        message.setFrom(from);
        message.setTo(email);
        message.setSubject("RecallDesk 邮箱验证码");
        message.setText("""
                你的 RecallDesk 验证码是：%s

                它 %d 分钟内有效，且只能使用一次。
                如果不是你本人在注册，忽略这封邮件即可。
                """.formatted(code, validMinutes));
        try {
            mailSender.send(message);
        } catch (MailException exc) {
            throw new IllegalStateException("验证码邮件发送失败: " + exc.getMessage(), exc);
        }
    }
}
