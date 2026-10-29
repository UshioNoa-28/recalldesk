package com.recalldesk.infrastructure.storage;

import com.recalldesk.domain.port.persistence.DocumentFileStorage;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * 本地磁盘上的原始文件：以内部 ID 作文件名放在 data/uploads/。
 *
 * 用 ID 而不是原名，是因为原名里可能有路径分隔符、也可能重名互相覆盖；名字本身另存在
 * documents.name，展示归展示、落盘归落盘。
 */
@Component
public class LocalFileStorage implements DocumentFileStorage {

    private static final String UPLOAD_DIR = "uploads";

    private final Path root;

    public LocalFileStorage(@Value("${recalldesk.data-dir:data}") String root) {
        this.root = Path.of(root).toAbsolutePath().normalize();
    }

    @Override
    public String save(String documentId, byte[] content) {
        Path uploadDir = root.resolve(UPLOAD_DIR);
        try {
            Files.createDirectories(uploadDir);
            Files.write(resolve(uploadDir.getFileName().toString() + "/" + documentId), content);
        } catch (IOException e) {
            throw new UncheckedIOException("写入上传文件失败: " + documentId, e);
        }
        return UPLOAD_DIR + "/" + documentId;
    }

    @Override
    public byte[] read(String storageKey) {
        try {
            return Files.readAllBytes(resolve(storageKey));
        } catch (IOException e) {
            throw new UncheckedIOException("读取上传文件失败: " + storageKey, e);
        }
    }

    @Override
    public void delete(String storageKey) {
        try {
            Files.deleteIfExists(resolve(storageKey));
        } catch (IOException e) {
            throw new UncheckedIOException("删除上传文件失败: " + storageKey, e);
        }
    }

    /**
     * storageKey 拼进路径前先归一，越界即拒。
     *
     * key 是我们自己写进去的（uploads/&lt;uuid&gt;），但 read/delete 的入参来自请求驱动的
     * 一次数据库取值，中间隔了 worker 与手工修数据的可能——一个 ".." 就能读到项目外的文件，
     * 这层检查便宜，不留这个口子更便宜。
     */
    private Path resolve(String storageKey) {
        Path target = root.resolve(storageKey).normalize();
        if (!target.startsWith(root)) {
            throw new IllegalArgumentException("storage_key 越出存储根目录: " + storageKey);
        }
        return target;
    }
}
