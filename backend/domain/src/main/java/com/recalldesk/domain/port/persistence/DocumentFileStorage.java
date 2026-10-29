package com.recalldesk.domain.port.persistence;

/**
 * 原始文件保存与读取能力。
 *
 * 磁盘上的原件才是权威，chunks 表里的文本只是派生副本——所以这里只管字节进字节出，
 * 怎么切、怎么编码都不归它管。
 */
public interface DocumentFileStorage {

    /** 保存文件并返回 storage_key（后续 read/delete 用它定位）。 */
    String save(String documentId, byte[] content);

    /** 按 storageKey 读取原始文件。 */
    byte[] read(String storageKey);

    /** 删除原始文件；文件不存在也视为成功（幂等）。 */
    void delete(String storageKey);
}
