package com.recalldesk.interfaces.web;

import com.recalldesk.application.document.DocumentService;
import com.recalldesk.application.search.dto.SearchOutcome;
import com.recalldesk.domain.Page;
import com.recalldesk.domain.documents.Document;
import com.recalldesk.application.document.dto.DocumentContent;
import com.recalldesk.domain.retrieval.ChunkRecord;
import com.recalldesk.application.search.dto.SearchProfile;
import com.recalldesk.interfaces.security.AuthenticatedUser;
import com.recalldesk.interfaces.web.dto.DocumentDtos.DocumentChunks;
import com.recalldesk.interfaces.web.dto.DocumentDtos.DocumentCreated;
import com.recalldesk.interfaces.web.dto.DocumentDtos.DocumentDeleted;
import com.recalldesk.interfaces.web.dto.DocumentDtos.DocumentList;
import com.recalldesk.interfaces.web.dto.DocumentDtos.DocumentView;
import com.recalldesk.interfaces.web.dto.DocumentDtos.SearchResult;
import java.io.IOException;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import com.recalldesk.domain.exception.indexing.EmptyContentException;

/**
 * 文档相关 HTTP 路由：8 条，每条都要 access 令牌且只作用于调用方自己的数据。
 * 文档 id 是别人的 UUID 时返回 404 而不是 403，不承认对方资源存在。
 *
 * 只做契约搬运：参数校验（FastAPI 的 Query 约束与 422 信封）、把服务返回值翻成
 * 出参形状、把异常翻成对应状态码与 detail。业务判断一律在 DocumentService，
 * 归属判断也一样——这里只负责把 caller.userId() 递下去。
 */
@RestController
public class DocumentController {

    /** 上传白名单：用户裁决只收 .txt/.md（settings.py 里那份旧默认值含 pdf/html 是历史残留）。 */
    private static final List<String> ALLOWED_SUFFIXES = List.of(".txt", ".md");
    /** 10 MiB。 */
    private static final long MAX_UPLOAD_BYTES = 10L * 1024 * 1024;

    private final DocumentService documentService;

    public DocumentController(DocumentService documentService) {
        this.documentService = documentService;
    }

    /**
     * 上传文件：存原文 + PG 元数据 + 出箱任务；分块/embedding/进索引都在后台 worker。
     *
     * 捕获顺序有讲究：UTF-8（400，必须先于通用 ValueError）→ 内容问题（400）→ 兜底 500。
     */
    @PostMapping("/documents")
    public DocumentCreated upload(
            AuthenticatedUser caller,
            @RequestParam(name = "file", required = false) MultipartFile file) {
        if (file == null) {
            FastApiValidation.Errors errors = new FastApiValidation.Errors();
            errors.add(FastApiValidation.missing(List.of("body", "file")));
            errors.throwIfAny();
        }
        String filename = safeFilename(file.getOriginalFilename() == null ? "" : file.getOriginalFilename());
        byte[] content = readBytes(file);
        validateUpload(filename, content);

        try {
            return created(documentService.ingest(filename, content, file.getContentType(), caller.userId()));
        } catch (RuntimeException exc) {
            throw uploadFailure(exc);
        }
    }

    /** 分页列出调用方自己的文档。 */
    @GetMapping("/documents")
    public DocumentList list(
            AuthenticatedUser caller,
            @RequestParam(required = false) String page,
            @RequestParam(name = "page_size", required = false) String pageSize) {
        FastApiValidation.Errors errors = new FastApiValidation.Errors();
        int resolvedPage = orDefault(FastApiValidation.intQuery("page", page, 1, 1, null, errors), 1);
        int resolvedPageSize = orDefault(FastApiValidation.intQuery("page_size", pageSize, 20, 1, 100, errors), 20);
        errors.throwIfAny();

        Page<Document> result = documentService.list(caller.userId(), resolvedPage, resolvedPageSize);
        return new DocumentList(result.items().stream().map(DocumentController::view).toList(),
                result.total(), resolvedPage, resolvedPageSize);
    }

    /** 查看单个文档。 */
    @GetMapping("/documents/{document_id}")
    public DocumentView detail(AuthenticatedUser caller, @PathVariable("document_id") String documentId) {
        return view(documentService.get(caller.userId(), documentId));
    }

    /**
     * 检索知识库。两个开关对应 run 级消融配方，全关 = dense+sparse RRF 裸检索。
     *
     * body 键序：query、hits，只有 channels=true 才追加 channels。
     */
    @GetMapping("/search")
    public SearchResult search(
            AuthenticatedUser caller,
            @RequestParam(required = false) String q,
            @RequestParam(name = "top_k", required = false) String topK,
            @RequestParam(required = false) String rewrite,
            @RequestParam(required = false) String rerank,
            @RequestParam(required = false) String channels) {
        FastApiValidation.Errors errors = new FastApiValidation.Errors();
        if (q == null) {
            errors.add(FastApiValidation.missing(List.of("query", "q")));
        } else if (q.isEmpty()) {
            errors.add(FastApiValidation.stringTooShort(List.of("query", "q"), q, 1));
        }
        Integer resolvedTopK = FastApiValidation.intQuery("top_k", topK, null, 1, 50, errors);
        boolean resolvedRewrite = Boolean.TRUE.equals(FastApiValidation.boolQuery("rewrite", rewrite, true, errors));
        boolean resolvedRerank = Boolean.TRUE.equals(FastApiValidation.boolQuery("rerank", rerank, true, errors));
        boolean resolvedChannels = Boolean.TRUE.equals(FastApiValidation.boolQuery("channels", channels, false, errors));
        errors.throwIfAny();

        SearchOutcome outcome = documentService.search(
                q, resolvedTopK, new SearchProfile(resolvedRewrite, resolvedRerank, null), caller.userId());
        return new SearchResult(
                q, outcome.hits(), resolvedChannels ? outcome.channels() : null);
    }

    /** 列出文档的全部分块（以向量库为准）。 */
    @GetMapping("/documents/{document_id}/chunks")
    public DocumentChunks chunks(AuthenticatedUser caller, @PathVariable("document_id") String documentId) {
        List<ChunkRecord> chunks = documentService.chunks(caller.userId(), documentId);
        return new DocumentChunks(documentId, chunks.size(), chunks);
    }

    /** 读取/下载文档原始文本：text/plain，download=true 时以附件形式给。 */
    @GetMapping("/documents/{document_id}/content")
    public ResponseEntity<String> content(
            AuthenticatedUser caller,
            @PathVariable("document_id") String documentId,
            @RequestParam(required = false) String download) {
        FastApiValidation.Errors errors = new FastApiValidation.Errors();
        boolean resolvedDownload = Boolean.TRUE.equals(FastApiValidation.boolQuery("download", download, false, errors));
        errors.throwIfAny();

        DocumentContent content = documentService.content(caller.userId(), documentId);
        ResponseEntity.BodyBuilder response = ResponseEntity.ok()
                .contentType(new MediaType(MediaType.TEXT_PLAIN, StandardCharsets.UTF_8));
        if (resolvedDownload) {
            response.header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + content.name() + "\"");
        }
        return response.body(content.text());
    }

    /** 重新索引：FAILED 文档救回来、SUCCESS 文档在改分块/嵌入参数后重建。 */
    @PostMapping("/documents/{document_id}/reindex")
    public DocumentCreated reindex(AuthenticatedUser caller, @PathVariable("document_id") String documentId) {
        Document document = documentService.reindex(caller.userId(), documentId);
        return new DocumentCreated(document.id(), document.name(), document.status().wire());
    }

    /** 删除文档：PG 元数据、引用题与受影响的评测 run 同事务删除，本地文件 best-effort。 */
    @DeleteMapping("/documents/{document_id}")
    public DocumentDeleted delete(AuthenticatedUser caller, @PathVariable("document_id") String documentId) {
        int removedItems = documentService.delete(caller.userId(), documentId);
        return new DocumentDeleted(documentId, true, removedItems);
    }

    // ---- 路由内的 HTTP 契约细节（不是业务判断） ----

    /** 上传成功与幂等重放共用同一个出参形状：重放不是另一种资源。 */
    private static DocumentCreated created(Document document) {
        return new DocumentCreated(document.id(), document.name(), document.status().wire());
    }

    /** 捕获顺序：空内容 → UTF-8 → 其它 ValueError。 */
    private static RuntimeException uploadFailure(RuntimeException exc) {
        if (exc instanceof EmptyContentException empty) {
            // 切不出分块是内容本身的问题 → 400 用服务原话
            return new ApiError(400, empty.getMessage());
        }
        if (exc instanceof IllegalArgumentException illegal) {
            if (isUtf8Failure(illegal)) {
                // UTF-8 解码失败固定文案，且必须先于其它 ValueError 判断
                return new ApiError(400, "文件必须是 UTF-8 文本");
            }
            return illegal; // advice → 400 str(exc)
        }
        return new ApiError(500, "索引失败: " + exc.getMessage());
    }

    private static DocumentView view(Document document) {
        return new DocumentView(
                document.id(),
                document.name(),
                document.status().wire(),
                document.chunkCount(),
                IsoTime.format(document.createdAt()),
                IsoTime.format(document.indexedAt()),
                document.errorMessage());
    }

    private static String safeFilename(String filename) {
        String name = filename.strip();
        if (name.isEmpty()) {
            throw new ApiError(400, "文件名无效");
        }
        return name;
    }

    private static byte[] readBytes(MultipartFile file) {
        try {
            return file.getBytes();
        } catch (IOException exc) {
            throw new ApiError(500, "索引失败: " + exc.getMessage());
        }
    }

    /** 上传前校验：后缀 → 空内容 → 大小，顺序固定（先说改哪个，再说为什么）。 */
    private static void validateUpload(String filename, byte[] content) {
        String suffix = UploadFileNames.suffixOf(filename);
        if (!ALLOWED_SUFFIXES.contains(suffix)) {
            throw new ApiError(400, "不支持的文件类型: " + suffix);
        }
        if (content.length == 0) {
            throw new ApiError(400, "文件内容为空");
        }
        if (content.length > MAX_UPLOAD_BYTES) {
            throw new ApiError(413, "文件过大");
        }
    }

    /** Java 侧 UTF-8 解码失败是 CharacterCodingException（被应用层包成 IAE），据此与 ValueError 分档。 */
    private static boolean isUtf8Failure(Throwable error) {
        for (Throwable current = error; current != null; current = current.getCause()) {
            if (current instanceof CharacterCodingException) {
                return true;
            }
            if (current.getCause() == current) {
                break;
            }
        }
        return false;
    }

    private static int orDefault(Integer value, int fallback) {
        return value == null ? fallback : value;
    }
}
