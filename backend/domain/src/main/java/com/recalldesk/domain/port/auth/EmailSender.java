package com.recalldesk.domain.port.auth;

/**
 * 发一封验证码邮件。
 *
 * 端口只认「发给谁、码是多少、多久有效」，SMTP 主机、端口、TLS、发件人全在适配器与装配层——
 * 换供应商（QQ 邮箱 → 企业邮 → SES）不该动业务代码，也不该让 application 认识 javax.mail。
 *
 * 发信失败一律抛出：验证码没送到却告诉用户"已发送"，用户会白等十分钟再重来。
 */
public interface EmailSender {

    void sendVerificationCode(String email, String code, long validMinutes);
}
