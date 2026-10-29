import React, { useState, useEffect, useCallback, useRef } from 'react';
import { DocumentItem, DocumentStatus, TargetChunkLink } from '../../types';
import { api, formatErrorMessage, ChunkItem } from '../../api/client';
import { useToast } from '../../context/ToastContext';
import {
  FileText,
  Search,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Copy,
  Check,
  Target,
  Cpu,
  Trash2,
  Download,
  FileCode,
  X,
  Eye,
  RotateCw,
} from 'lucide-react';

interface DocumentExplorerProps {
  initialTarget?: TargetChunkLink | null;
  onClearTarget?: () => void;
  onNavigateToSearch?: () => void;
  refreshTrigger: number;
}

const getFileFormatBadge = (filename: string) => {
  const ext = filename.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'pdf':
      return (
        <span className="px-1.5 py-0.2 text-[9px] font-mono font-bold text-rose-700 bg-rose-50 border border-rose-200 rounded shrink-0">
          PDF
        </span>
      );
    case 'md':
      return (
        <span className="px-1.5 py-0.2 text-[9px] font-mono font-bold text-blue-700 bg-blue-50 border border-blue-200 rounded shrink-0">
          MD
        </span>
      );
    case 'csv':
      return (
        <span className="px-1.5 py-0.2 text-[9px] font-mono font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded shrink-0">
          CSV
        </span>
      );
    case 'html':
    case 'htm':
      return (
        <span className="px-1.5 py-0.2 text-[9px] font-mono font-bold text-amber-700 bg-amber-50 border border-amber-200 rounded shrink-0">
          HTML
        </span>
      );
    default:
      return (
        <span className="px-1.5 py-0.2 text-[9px] font-mono font-medium text-slate-600 bg-slate-100 border border-slate-200 rounded shrink-0">
          {ext?.toUpperCase() || 'TXT'}
        </span>
      );
  }
};

export const DocumentExplorer: React.FC<DocumentExplorerProps> = ({
  initialTarget,
  onClearTarget,
  onNavigateToSearch,
  refreshTrigger,
}) => {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const pageSize = 15;
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [chunkFilterTerm, setChunkFilterTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [selectedDoc, setSelectedDoc] = useState<DocumentItem | null>(null);
  const [docChunks, setDocChunks] = useState<ChunkItem[] | null>(null);
  const [loadingChunks, setLoadingChunks] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [copiedChunkIdx, setCopiedChunkIdx] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [downloadingDocId, setDownloadingDocId] = useState<string | null>(null);
  const [confirmDeleteDoc, setConfirmDeleteDoc] = useState<DocumentItem | null>(null);
  const [reindexingDocId, setReindexingDocId] = useState<string | null>(null);
  const [viewingFullContent, setViewingFullContent] = useState(false);
  const [fullContentText, setFullContentText] = useState<string | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);
  const [activeChunkTarget, setActiveChunkTarget] = useState<TargetChunkLink | null>(
    initialTarget || null
  );

  const { addToast } = useToast();
  const pollingRef = useRef<number | null>(null);
  const selectedDocRef = useRef<DocumentItem | null>(selectedDoc);
  const chunkRefs = useRef<Record<number, HTMLDivElement | null>>({});

  useEffect(() => {
    selectedDocRef.current = selectedDoc;
  }, [selectedDoc]);

  // Handle Initial Target from Hash or props
  useEffect(() => {
    if (initialTarget) {
      setActiveChunkTarget(initialTarget);
      if (initialTarget.documentId) {
        api.getDocument(initialTarget.documentId).then((doc) => {
          setSelectedDoc(doc);
          loadDocumentChunks(doc.id);
        }).catch(() => {
          // Ignore
        });
      }
    }
  }, [initialTarget]);

  // Fetch Documents List
  const fetchDocuments = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        const res = await api.listDocuments(page, pageSize);
        setDocuments(res.items || []);
        setTotal(res.total || 0);

        if (selectedDocRef.current) {
          const updated = (res.items || []).find((d) => d.id === selectedDocRef.current?.id);
          if (updated) {
            setSelectedDoc(updated);
            if (updated.status === 'success' && (!docChunks || docChunks.length === 0)) {
              loadDocumentChunks(updated.id);
            }
          }
        }
      } catch (err) {
        if (!silent) {
          addToast('error', '加载文档列表失败', formatErrorMessage(err));
        }
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [page, docChunks, addToast]
  );

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments, refreshTrigger]);

  // Auto Polling for pending documents
  useEffect(() => {
    if (autoRefresh) {
      pollingRef.current = window.setInterval(() => {
        const hasPending = documents.some((d) => d.status === 'pending');
        const selectedIsPending = selectedDocRef.current?.status === 'pending';
        if (hasPending || selectedIsPending) {
          fetchDocuments(true);
        }
      }, 3000);
    }
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [autoRefresh, documents, fetchDocuments]);

  // Load Chunks for a specific Document
  const loadDocumentChunks = async (documentId: string) => {
    setLoadingChunks(true);
    try {
      const res = await api.getDocumentChunks(documentId);
      setDocChunks(res.chunks || []);
    } catch {
      setDocChunks([]);
    } finally {
      setLoadingChunks(false);
    }
  };

  const handleSelectDoc = (doc: DocumentItem) => {
    setSelectedDoc(doc);
    setDocChunks(null);
    setChunkFilterTerm('');
    window.location.hash = `#/documents/${doc.id}`;
    if (doc.status === 'success') {
      loadDocumentChunks(doc.id);
    }
  };

  const handleReindex = async (doc: DocumentItem) => {
    setReindexingDocId(doc.id);
    try {
      const res = await api.reindexDocument(doc.id);
      addToast(
        'success',
        '已重新提交索引任务',
        `文档「${res.name}」已提交后台，正在重新分块与生成向量...`
      );
      await fetchDocuments();
      if (selectedDoc?.id === doc.id) {
        setSelectedDoc({ ...selectedDoc, status: 'pending' });
        setDocChunks(null);
      }
    } catch (err) {
      addToast('error', '重建索引失败', formatErrorMessage(err));
    } finally {
      setReindexingDocId(null);
    }
  };

  const executeDeleteDoc = async (doc: DocumentItem) => {
    setDeleting(true);
    try {
      await api.deleteDocument(doc.id);
      addToast('success', '文档已删除', `「${doc.name}」及其切片已彻底删除`);
      if (selectedDoc?.id === doc.id) {
        setSelectedDoc(null);
        setDocChunks(null);
        if (onClearTarget) onClearTarget();
        window.location.hash = '#/documents';
      }
      setConfirmDeleteDoc(null);
      await fetchDocuments();
    } catch (err) {
      addToast('error', '删除失败', formatErrorMessage(err));
    } finally {
      setDeleting(false);
    }
  };

  const handleCopyText = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
    addToast('info', '已复制到剪贴板');
  };

  const handleCopyChunkText = (text: string, chunkIdx: number) => {
    navigator.clipboard.writeText(text);
    setCopiedChunkIdx(chunkIdx);
    setTimeout(() => setCopiedChunkIdx(null), 2000);
    addToast('info', '切片原文已复制');
  };

  const handleCopyJsonlEvidence = (chunk: ChunkItem) => {
    if (!selectedDoc) return;
    const sample = JSON.stringify({
      document_id: selectedDoc.id,
      chunk_index: chunk.chunk_index,
    });
    navigator.clipboard.writeText(sample);
    addToast('success', '已复制 JSONL 证据对象', '可直接粘贴到 .jsonl 文件的 evidence 数组中');
  };

  const handleDownloadDoc = async (doc: DocumentItem) => {
    setDownloadingDocId(doc.id);
    try {
      await api.downloadDocument(doc.id, doc.name);
      addToast('success', '下载已开始', `正在下载「${doc.name}」`);
    } catch (err) {
      addToast('error', '下载失败', formatErrorMessage(err));
    } finally {
      setDownloadingDocId(null);
    }
  };

  const handleViewFullContent = async (docId: string) => {
    setViewingFullContent(true);
    setLoadingContent(true);
    try {
      const text = await api.getDocumentContent(docId);
      setFullContentText(text);
    } catch (err) {
      addToast('error', '读取原文失败', formatErrorMessage(err));
      setViewingFullContent(false);
    } finally {
      setLoadingContent(false);
    }
  };

  const getStatusBadge = (status: DocumentStatus) => {
    switch (status) {
      case 'success':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
            <CheckCircle2 className="w-3 h-3" />
            SUCCESS
          </span>
        );
      case 'pending':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-amber-50 text-amber-700 border border-amber-200">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-ping" />
            PENDING
          </span>
        );
      case 'failed':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-rose-50 text-rose-700 border border-rose-200">
            <AlertCircle className="w-3 h-3" />
            FAILED
          </span>
        );
    }
  };

  const filteredDocs = documents.filter((doc) => {
    const matchesSearch = doc.name.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesStatus = statusFilter === 'all' || doc.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const totalPages = Math.ceil(total / pageSize) || 1;

  const filteredChunks = (docChunks || []).filter((c) => {
    if (!chunkFilterTerm.trim()) return true;
    return c.text.toLowerCase().includes(chunkFilterTerm.toLowerCase());
  });

  return (
    <div className="flex-1 flex flex-col md:flex-row min-h-0 bg-slate-50 overflow-hidden relative">
      {/* Left Master Pane: Document List */}
      <div className="w-full md:w-5/12 lg:w-4/12 border-r border-slate-200 flex flex-col bg-white min-h-0">
        {/* Top filter / search bar */}
        <div className="p-3.5 border-b border-slate-200 space-y-2.5 bg-slate-50/70">
          <div className="flex items-center justify-between text-xs">
            <span className="font-mono font-bold text-slate-800 flex items-center gap-1.5">
              <FileText className="w-3.5 h-3.5 text-blue-600" />
              <span>知识库文档 ({total})</span>
            </span>

            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1 text-[11px] font-mono text-slate-500 cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoRefresh}
                  onChange={(e) => setAutoRefresh(e.target.checked)}
                  className="rounded bg-white border-slate-300 text-blue-600 w-3 h-3"
                />
                <span>轮询</span>
              </label>

              <button
                onClick={() => fetchDocuments(false)}
                disabled={loading}
                className="p-1 rounded bg-white hover:bg-slate-100 border border-slate-200 text-slate-500 hover:text-slate-800 transition-colors cursor-pointer"
                title="刷新列表"
              >
                <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            <div className="relative flex-1">
              <Search className="w-3 h-3 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="搜索文档名称..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full pl-7 pr-2.5 py-1.5 bg-white border border-slate-300 rounded text-xs font-mono text-slate-900 placeholder-slate-400 focus:outline-none focus:border-blue-600 focus:ring-1 focus:ring-blue-100"
              />
            </div>

            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-2.5 py-1.5 bg-white border border-slate-300 rounded text-xs font-mono text-slate-700 focus:outline-none cursor-pointer"
            >
              <option value="all">全部</option>
              <option value="success">SUCCESS</option>
              <option value="pending">PENDING</option>
              <option value="failed">FAILED</option>
            </select>
          </div>
        </div>

        {/* Document Items List */}
        <div className="flex-1 overflow-y-auto divide-y divide-slate-100">
          {loading && documents.length === 0 ? (
            <div className="p-8 text-center text-slate-400 font-mono text-xs">
              <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-blue-600" />
              正在加载文档列表...
            </div>
          ) : filteredDocs.length === 0 ? (
            <div className="p-8 text-center text-slate-400 font-mono text-xs">
              暂无匹配的知识库文档
            </div>
          ) : (
            filteredDocs.map((doc) => {
              const isSelected = selectedDoc?.id === doc.id;
              return (
                <div
                  key={doc.id}
                  onClick={() => handleSelectDoc(doc)}
                  className={`p-3.5 cursor-pointer transition-colors ${
                    isSelected
                      ? 'bg-blue-50/70 border-l-3 border-l-blue-600'
                      : 'hover:bg-slate-50'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 truncate min-w-0">
                      {getFileFormatBadge(doc.name)}
                      <span className="text-sm font-mono text-slate-900 font-semibold truncate">
                        {doc.name}
                      </span>
                    </div>
                    {getStatusBadge(doc.status)}
                  </div>

                  <div className="flex items-center justify-between mt-2 text-xs font-mono text-slate-500">
                    <span>切片: {doc.chunk_count} 块</span>
                    <span>
                      {doc.created_at
                        ? new Date(doc.created_at).toLocaleTimeString('zh-CN', {
                            hour: '2-digit',
                            minute: '2-digit',
                          })
                        : '—'}
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Pagination bar */}
        <div className="p-3 border-t border-slate-200 flex items-center justify-between text-xs font-mono bg-slate-50">
          <span className="text-slate-500 text-[11px]">
            第 {page} / {totalPages} 页
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="p-1 rounded bg-white hover:bg-slate-100 border border-slate-200 text-slate-600 disabled:opacity-40 cursor-pointer disabled:cursor-not-allowed"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="p-1 rounded bg-white hover:bg-slate-100 border border-slate-200 text-slate-600 disabled:opacity-40 cursor-pointer disabled:cursor-not-allowed"
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Right Detail Pane: Chunks & Meta */}
      <div className="flex-1 flex flex-col bg-slate-50 overflow-y-auto p-6 space-y-4">
        {selectedDoc ? (
          <div className="max-w-5xl space-y-4">
            {/* Target chunk alert banner */}
            {activeChunkTarget && (
              <div className="p-3 bg-blue-50 border border-blue-200 rounded-xl flex items-center justify-between text-xs font-mono text-blue-900">
                <div className="flex items-center gap-2">
                  <Target className="w-4 h-4 text-blue-600 shrink-0" />
                  <span>
                    已定位到切片: <strong>#chunk_{(activeChunkTarget.chunkIndex ?? 0) + 1}</strong>
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {onNavigateToSearch && (
                    <button
                      onClick={onNavigateToSearch}
                      className="px-2 py-0.5 rounded bg-blue-100 hover:bg-blue-200 text-blue-800 text-[11px] font-semibold transition-colors cursor-pointer"
                    >
                      返回检索控制台
                    </button>
                  )}
                  <button
                    onClick={() => {
                      setActiveChunkTarget(null);
                      if (onClearTarget) onClearTarget();
                      window.location.hash = `#/documents/${selectedDoc.id}`;
                    }}
                    className="text-slate-400 hover:text-slate-700 cursor-pointer"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )}

            {/* Document Header Card */}
            <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-4 shadow-xs">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2.5">
                    {getFileFormatBadge(selectedDoc.name)}
                    <h2 className="text-base font-bold font-mono text-slate-900 break-all">
                      {selectedDoc.name}
                    </h2>
                  </div>
                  <div className="flex items-center gap-2 text-xs font-mono text-slate-500">
                    <span>UUID: {selectedDoc.id}</span>
                    <button
                      onClick={() => handleCopyText(selectedDoc.id, 'docId')}
                      className="hover:text-slate-800 transition-colors cursor-pointer"
                      title="复制文档 ID"
                    >
                      {copiedId === 'docId' ? (
                        <Check className="w-3.5 h-3.5 text-emerald-600" />
                      ) : (
                        <Copy className="w-3.5 h-3.5 text-slate-400" />
                      )}
                    </button>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {getStatusBadge(selectedDoc.status)}

                  {/* Read Raw Content */}
                  <button
                    onClick={() => handleViewFullContent(selectedDoc.id)}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs font-mono text-slate-700 hover:text-slate-900 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-md transition-colors cursor-pointer"
                    title="在弹窗中浏览文档原始文本"
                  >
                    <Eye className="w-3.5 h-3.5 text-slate-500" />
                    <span>查看原文</span>
                  </button>

                  {/* Download Raw File */}
                  <button
                    onClick={() => handleDownloadDoc(selectedDoc)}
                    disabled={downloadingDocId === selectedDoc.id}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs font-mono text-slate-700 hover:text-slate-900 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-md transition-colors cursor-pointer disabled:opacity-50"
                    title="下载原始文本原件"
                  >
                    <Download className={`w-3.5 h-3.5 text-slate-500 ${downloadingDocId === selectedDoc.id ? 'animate-bounce' : ''}`} />
                    <span>{downloadingDocId === selectedDoc.id ? '下载中...' : '下载原件'}</span>
                  </button>

                  {/* Reindex Button */}
                  <button
                    onClick={() => handleReindex(selectedDoc)}
                    disabled={reindexingDocId === selectedDoc.id || selectedDoc.status === 'pending'}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs font-mono text-blue-700 hover:text-blue-800 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-md transition-colors cursor-pointer disabled:opacity-50"
                    title="重新触发该文档的文本分块与向量化写入"
                  >
                    <RotateCw
                      className={`w-3.5 h-3.5 text-blue-600 ${
                        reindexingDocId === selectedDoc.id ? 'animate-spin' : ''
                      }`}
                    />
                    <span>重建索引</span>
                  </button>

                  {/* Delete Button */}
                  <button
                    onClick={() => setConfirmDeleteDoc(selectedDoc)}
                    disabled={deleting}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs font-mono text-rose-600 hover:text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 rounded-md transition-colors cursor-pointer disabled:opacity-50"
                    title="删除该文档及其全部关联切片"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>删除</span>
                  </button>
                </div>
              </div>

              {selectedDoc.error_message && (
                <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-xs font-mono text-rose-700 flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0 text-rose-600 mt-0.5" />
                  <div>
                    <span className="font-bold">错误信息:</span> {selectedDoc.error_message}
                  </div>
                </div>
              )}

              {/* Document Meta Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-3 border-t border-slate-100 text-xs font-mono">
                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <span className="text-slate-500 text-[10px] block mb-0.5">切片总数</span>
                  <span className="text-blue-700 font-bold text-base">
                    {selectedDoc.chunk_count} 块
                  </span>
                </div>

                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <span className="text-slate-500 text-[10px] block mb-0.5">创建时间</span>
                  <span className="text-slate-800 text-[11px] truncate block">
                    {selectedDoc.created_at ? new Date(selectedDoc.created_at).toLocaleString() : '—'}
                  </span>
                </div>

                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <span className="text-slate-500 text-[10px] block mb-0.5">索引完成时间</span>
                  <span className="text-slate-800 text-[11px] truncate block">
                    {selectedDoc.indexed_at ? new Date(selectedDoc.indexed_at).toLocaleString() : '—'}
                  </span>
                </div>

                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <span className="text-slate-500 text-[10px] block mb-0.5">存储与分块</span>
                  <span className="text-emerald-700 font-medium text-[11px] block">
                    PG pgvector + BM25
                  </span>
                </div>
              </div>
            </div>

            {/* Chunks Explorer Section */}
            <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-4 shadow-xs">
              <div className="flex flex-wrap items-center justify-between gap-3 text-xs font-mono pb-3 border-b border-slate-100">
                <div className="flex items-center gap-2 text-slate-800 font-bold">
                  <FileCode className="w-4 h-4 text-blue-600" />
                  <span>
                    切片内容浏览 ({docChunks ? `${filteredChunks.length} / ${docChunks.length}` : '—'} 块)
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  {docChunks && docChunks.length > 0 && (
                    <div className="relative">
                      <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                      <input
                        type="text"
                        value={chunkFilterTerm}
                        onChange={(e) => setChunkFilterTerm(e.target.value)}
                        placeholder="在切片文本中搜索..."
                        className="pl-7 pr-2.5 py-1 text-xs font-mono bg-slate-50 border border-slate-200 rounded-md focus:outline-none focus:border-blue-600 focus:bg-white text-slate-800 placeholder-slate-400"
                      />
                    </div>
                  )}
                </div>
              </div>

              {/* Real Chunks List */}
              {selectedDoc.status === 'pending' ? (
                <div className="py-20 px-4 flex flex-col items-center justify-center text-center space-y-4">
                  <div className="relative flex items-center justify-center">
                    <div className="w-12 h-12 rounded-full border-3 border-amber-200 border-t-amber-600 animate-spin" />
                    <Cpu className="w-5 h-5 text-amber-600 absolute animate-pulse" />
                  </div>
                  <div className="space-y-1.5 max-w-sm">
                    <h4 className="text-xs font-bold font-mono text-slate-800">
                      文档正在切片与生成向量索引...
                    </h4>
                    <p className="text-[11px] font-mono text-slate-500 leading-relaxed">
                      后台 Worker 正在解析文本分块并生成稠密与稀疏向量，索引完成后将自动呈现切片列表。
                    </p>
                  </div>
                </div>
              ) : loadingChunks ? (
                <div className="p-8 text-center text-slate-400 font-mono text-xs">
                  <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-blue-600" />
                  正在从检索索引加载全部切片文本...
                </div>
              ) : filteredChunks.length > 0 ? (
                <div className="space-y-3">
                  {filteredChunks.map((chunk) => {
                    const isFocused = activeChunkTarget?.chunkIndex === chunk.chunk_index;
                    const lineCount = chunk.text.split('\n').length;

                    return (
                      <div
                        key={chunk.chunk_index}
                        ref={(el) => {
                          chunkRefs.current[chunk.chunk_index] = el;
                        }}
                        className={`p-4 rounded-xl border transition-all ${
                          isFocused
                            ? 'bg-blue-50/70 border-2 border-blue-600 shadow-md'
                            : 'bg-slate-50/70 border-slate-200 hover:border-slate-300'
                        }`}
                      >
                        {/* Chunk Header */}
                        <div className="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-slate-200/80 text-xs font-mono">
                          <div className="flex items-center gap-2">
                            <span
                              className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                                isFocused
                                  ? 'bg-blue-600 text-white'
                                  : 'bg-white border border-slate-200 text-slate-800'
                              }`}
                            >
                              Chunk #{chunk.chunk_index + 1}
                            </span>
                            <span className="text-[11px] text-slate-400">
                              {chunk.text.length} 字符 • {lineCount} 行
                            </span>
                          </div>

                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => handleCopyJsonlEvidence(chunk)}
                              className="flex items-center gap-1 px-2 py-0.5 rounded bg-purple-50 hover:bg-purple-100 border border-purple-200 text-purple-700 text-xs font-medium transition-colors cursor-pointer"
                              title="复制此切片的 JSONL 证据对象（包含 document_id 与 chunk_index）"
                            >
                              <Copy className="w-3.5 h-3.5 text-purple-600" />
                              <span>复制评测证据</span>
                            </button>

                            <button
                              onClick={() => handleCopyChunkText(chunk.text, chunk.chunk_index)}
                              className="flex items-center gap-1 px-2 py-0.5 rounded bg-white hover:bg-slate-100 border border-slate-200 text-slate-600 hover:text-slate-900 text-[11px] transition-colors cursor-pointer"
                              title="复制该切片全文文本"
                            >
                              {copiedChunkIdx === chunk.chunk_index ? (
                                <Check className="w-3 h-3 text-emerald-600" />
                              ) : (
                                <Copy className="w-3.5 h-3.5 text-slate-400" />
                              )}
                              <span>{copiedChunkIdx === chunk.chunk_index ? '已复制' : '复制全文'}</span>
                            </button>
                          </div>
                        </div>

                        {/* Chunk Content */}
                        <pre className="mt-3 text-sm font-mono text-slate-800 leading-relaxed whitespace-pre-wrap break-words bg-white p-3.5 rounded-lg border border-slate-200 selection:bg-blue-100">
                          {chunk.text}
                        </pre>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="p-8 text-center text-slate-400 font-mono text-xs">
                  {selectedDoc.status === 'failed'
                    ? '文档索引失败，暂无切片内容'
                    : '该文档暂无切片数据'}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-slate-400 font-mono text-xs space-y-2">
            <FileText className="w-8 h-8 text-slate-300" />
            <p>从左侧选择一篇文档，查看其解析与切片详情</p>
          </div>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      {confirmDeleteDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-sm w-full p-5 shadow-xl space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-rose-50 border border-rose-200 flex items-center justify-center text-rose-600">
                <Trash2 className="w-4 h-4" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-slate-900 font-mono">确认删除文档？</h3>
                <p className="text-xs text-slate-500 font-mono">该操作不可恢复</p>
              </div>
            </div>

            <p className="text-xs font-mono text-slate-600 bg-slate-50 p-3 rounded-lg border border-slate-200 break-all">
              文档「{confirmDeleteDoc.name}」的所有切片与检索索引都将被彻底清除。
            </p>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100 text-xs font-mono">
              <button
                onClick={() => setConfirmDeleteDoc(null)}
                className="px-3 py-1.5 rounded-lg text-slate-600 hover:bg-slate-100 transition-colors cursor-pointer"
              >
                取消
              </button>
              <button
                onClick={() => executeDeleteDoc(confirmDeleteDoc)}
                disabled={deleting}
                className="px-3.5 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white font-semibold shadow-xs transition-all cursor-pointer"
              >
                {deleting ? '正在删除...' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Full Content View Modal */}
      {viewingFullContent && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-3xl w-full p-6 shadow-2xl flex flex-col max-h-[85vh] space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-blue-600" />
                <h3 className="text-sm font-bold text-slate-900 font-mono">
                  文档原文浏览：{selectedDoc?.name}
                </h3>
              </div>
              <button
                onClick={() => {
                  setViewingFullContent(false);
                  setFullContentText(null);
                }}
                className="text-slate-400 hover:text-slate-700 p-1 rounded-lg hover:bg-slate-100 transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto bg-slate-50 p-4 rounded-xl border border-slate-200">
              {loadingContent ? (
                <div className="py-20 text-center text-slate-400 font-mono text-xs">
                  <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2 text-blue-600" />
                  正在读取文档原文内容...
                </div>
              ) : fullContentText ? (
                <pre className="text-xs font-mono text-slate-800 whitespace-pre-wrap leading-relaxed">
                  {fullContentText}
                </pre>
              ) : (
                <div className="py-10 text-center text-slate-400 font-mono text-xs">
                  暂无文本内容
                </div>
              )}
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-slate-100 text-xs font-mono">
              <span className="text-slate-400 text-[11px]">
                {fullContentText ? `共 ${fullContentText.length} 字符` : ''}
              </span>
              <button
                onClick={() => {
                  setViewingFullContent(false);
                  setFullContentText(null);
                }}
                className="px-4 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold rounded-lg transition-colors cursor-pointer"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
