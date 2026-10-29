package com.recalldesk.interfaces.web;

import java.util.List;
import java.util.Map;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.resource.NoResourceFoundException;

/**
 * 框架级错误的信封：把"请求还没进到路由"的三类失败也翻成 {@code {"detail": ...}}。
 *
 * 这三条不归业务路由管，但契约上必须与 FastAPI 一致：
 * - 请求体不是 JSON → 422 json_invalid（FastAPI 同款 loc/msg，ctx.error 用解析器说明；
 *   ctx.error 给解析器自己的说明）
 * - 未匹配路径 → 404 {@code "Not Found"}
 * - 方法不对 → 405 {@code "Method Not Allowed"}
 *
 * 与 ApiExceptionAdvice 分成两个类：那边的映射是"业务异常 → 状态码"，
 * 这边是"框架层失败 → 信封"，改动理由不同，放一起会让两者互相牵制。
 *
 * {@code @Order(HIGHEST_PRECEDENCE)} 是必须的：那边有兜底的 Exception 处理器，
 * 多个 advice 混在一起时 Spring 按 advice 顺序找处理法，排后面就永远轮不到这里的精确匹配。
 */
@RestControllerAdvice
@Order(Ordered.HIGHEST_PRECEDENCE)
public class FrameworkExceptionAdvice {

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<Map<String, Object>> unreadable(HttpMessageNotReadableException exc) {
        String reason = exc.getMostSpecificCause().getMessage();
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY)
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("detail", List.of(FastApiValidation.jsonInvalid(reason))));
    }

    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<Map<String, Object>> notFound(NoResourceFoundException exc) {
        return body(HttpStatus.NOT_FOUND, "Not Found");
    }

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<Map<String, Object>> methodNotAllowed(HttpRequestMethodNotSupportedException exc) {
        return body(HttpStatus.METHOD_NOT_ALLOWED, "Method Not Allowed");
    }

    private static ResponseEntity<Map<String, Object>> body(HttpStatus status, Object detail) {
        return ResponseEntity.status(status).contentType(MediaType.APPLICATION_JSON).body(Map.of("detail", detail));
    }
}
