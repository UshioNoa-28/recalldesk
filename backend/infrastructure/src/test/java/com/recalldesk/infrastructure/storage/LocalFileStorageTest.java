package com.recalldesk.infrastructure.storage;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/** 本地文件存储测试（临时目录，不碰项目 data/）。 */
class LocalFileStorageTest {

    @TempDir
    Path root;

    @Test
    @DisplayName("存 → 读 → 删 走通，key 就是相对根目录的路径")
    void saveReadDeleteRoundTrip() {
        LocalFileStorage storage = new LocalFileStorage(root.toString());

        String storageKey = storage.save("doc-1", "hello".getBytes(StandardCharsets.UTF_8));

        assertThat(storageKey).isEqualTo("uploads/doc-1");
        assertThat(new String(storage.read(storageKey), StandardCharsets.UTF_8)).isEqualTo("hello");

        storage.delete(storageKey);
        assertThat(root.resolve(storageKey)).doesNotExist();
    }

    @Test
    @DisplayName("删不存在的文件不报错：删除要能被重投")
    void deleteMissingFileIsIdempotent() {
        new LocalFileStorage(root.toString()).delete("uploads/nope");
    }

    @Test
    @DisplayName("读不存在的文件报错，不返回空字节冒充空文档")
    void readMissingFileFails() {
        LocalFileStorage storage = new LocalFileStorage(root.toString());

        assertThatThrownBy(() -> storage.read("uploads/nope")).isInstanceOf(UncheckedIOException.class);
    }

    @Test
    @DisplayName("storage_key 里的 .. 不许越出存储根目录")
    void traversalOutsideRootRejected() {
        LocalFileStorage storage = new LocalFileStorage(root.toString());

        assertThatThrownBy(() -> storage.read("../secrets.env"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("越出存储根目录");
    }
}
