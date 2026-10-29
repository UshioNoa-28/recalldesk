package com.recalldesk.interfaces.web;

import com.recalldesk.domain.exception.users.BadCredentialsException;
import com.recalldesk.domain.exception.documents.DocumentNotFoundException;
import com.recalldesk.domain.exception.users.EmailCodeInvalidException;
import com.recalldesk.domain.exception.users.EmailCodeTooFrequentException;
import com.recalldesk.domain.exception.users.EmailTakenException;
import com.recalldesk.domain.exception.users.InvalidTokenException;
import com.recalldesk.domain.exception.eval.RunNotFoundException;
import com.recalldesk.domain.exception.eval.TestSetNotFoundException;
import com.recalldesk.domain.exception.users.UsernameTakenException;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * 错误翻译：所有响应体都是 {@code {"detail": ...}}（FastAPI 的 HTTPException 形状）。
 *
 * 这里只兜"各路由共用"的那几条：三种 404 文案各自独立（本来就是三句不同的
 * KeyError 文案，合一条会让前端分不出是哪个对象不存在）、
 * ValueError→400、以及校验失败→422。逐路由不同的 detail（上传的 UTF-8/索引失败文案、
 * "文档正在处理中"之类）留在路由里抛 {@link ApiError}，不让 advice 猜。
 *
 * 白标错误页关掉（application.yml 的 server.error.whitelabel.enabled），
 * 未匹配路径/方法的 404/405 也走这里的同款信封。
 */
@RestControllerAdvice
public class ApiExceptionAdvice {

    private static final Logger log = LoggerFactory.getLogger(ApiExceptionAdvice.class);

    /** 领域异常 → 404/409：三种 404 文案各自独立，不合并成一句通用的。 */
    @ExceptionHandler(DocumentNotFoundException.class)
    public ResponseEntity<Map<String, Object>> documentNotFound(DocumentNotFoundException exc) {
        return body(HttpStatus.NOT_FOUND, "文档不存在");
    }

    @ExceptionHandler(TestSetNotFoundException.class)
    public ResponseEntity<Map<String, Object>> testSetNotFound(TestSetNotFoundException exc) {
        return body(HttpStatus.NOT_FOUND, "评测集不存在");
    }

    @ExceptionHandler(RunNotFoundException.class)
    public ResponseEntity<Map<String, Object>> runNotFound(RunNotFoundException exc) {
        return body(HttpStatus.NOT_FOUND, "评测运行不存在");
    }

    /** 邮箱占用与验证码不对同为 400：都是注册这一举动不了，但文案要分得清（用户知道该改什么）。 */
    @ExceptionHandler(EmailTakenException.class)
    public ResponseEntity<Map<String, Object>> emailTaken(EmailTakenException exc) {
        return body(HttpStatus.BAD_REQUEST, "该邮箱已被注册");
    }

    @ExceptionHandler(EmailCodeInvalidException.class)
    public ResponseEntity<Map<String, Object>> emailCodeInvalid(EmailCodeInvalidException exc) {
        return body(HttpStatus.BAD_REQUEST, "验证码不正确或已过期");
    }

    /** 发码太勤 → 429 并带上 Retry-After（秒），客户端据此倒计时而不必自己猜。 */
    @ExceptionHandler(EmailCodeTooFrequentException.class)
    public ResponseEntity<Map<String, Object>> emailCodeTooFrequent(EmailCodeTooFrequentException exc) {
        return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS)
                .contentType(MediaType.APPLICATION_JSON)
                .header("Retry-After", String.valueOf(exc.retryAfterSeconds()))
                .body(Map.of("detail", exc.getMessage()));
    }

    /** 参数值不合法 → 400 用异常原话（重索引 PENDING、融合配方非法、坐标不存在都走这条）。 */
    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, Object>> valueError(IllegalArgumentException exc) {
        return body(HttpStatus.BAD_REQUEST, exc.getMessage());
    }

    /** DTO 注解校验失败 → 422，detail 是各字段文案用「；」拼起来的一句。 */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Map<String, Object>> invalidBody(MethodArgumentNotValidException exc) {
        String detail = exc.getBindingResult().getFieldErrors().stream()
                .map(error -> error.getDefaultMessage())
                .distinct()
                .collect(Collectors.joining("；"));
        return body(HttpStatus.UNPROCESSABLE_ENTITY, detail);
    }

    /**
     * 凭证不对 → 401。
     *
     * detail 是固定一句：用户名不存在与口令错给完全相同的响应，
     * 否则这个端点就是个用户名枚举接口。
     */
    @ExceptionHandler(BadCredentialsException.class)
    public ResponseEntity<Map<String, Object>> badCredentials(BadCredentialsException exc) {
        return body(HttpStatus.UNAUTHORIZED, exc.getMessage());
    }

    /** 令牌验不过 / 类型不对 / 令牌背后的账号没了 → 401，调用方该去刷新或重登。 */
    @ExceptionHandler(InvalidTokenException.class)
    public ResponseEntity<Map<String, Object>> invalidToken(InvalidTokenException exc) {
        return body(HttpStatus.UNAUTHORIZED, "登录状态已失效，请重新登录");
    }

    /** 用户名占用 → 409（这个可以照实说：它本来就是给正在注册的人看的）。 */
    @ExceptionHandler(UsernameTakenException.class)
    public ResponseEntity<Map<String, Object>> usernameTaken(UsernameTakenException exc) {
        return body(HttpStatus.CONFLICT, exc.getMessage());
    }

    /** 路由里显式抛的 HTTP 错误（状态码与 detail 都由抛出处决定）。 */
    @ExceptionHandler(ApiError.class)
    public ResponseEntity<Map<String, Object>> apiError(ApiError exc) {
        return ResponseEntity.status(exc.status()).contentType(MediaType.APPLICATION_JSON).body(Map.of("detail", exc.detail()));
    }

    /**
     * 兜底：未捕获的异常一律 500。正文仍给 {@code {"detail": ...}}，
     * 不把堆栈或内部细节漏给前端（日志里有完整的）。
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> unexpected(Exception exc, HttpServletRequest request) {
        log.error("未处理异常: {} {}", request.getMethod(), request.getRequestURI(), exc);
        return body(HttpStatus.INTERNAL_SERVER_ERROR, "Internal Server Error");
    }

    private static ResponseEntity<Map<String, Object>> body(HttpStatus status, Object detail) {
        return ResponseEntity.status(status).contentType(MediaType.APPLICATION_JSON).body(Map.of("detail", detail));
    }
}
