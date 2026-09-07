import React, { useState, useEffect, useCallback, useRef } from 'react';
import { DocumentItem, DocumentStatus, TargetChunkLink, TestSet } from '../../types';
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
  Layers,
  Target,
  ArrowLeft,
  Binary,
  Cpu,
  Trash2,
  Download,
  FileCode,
  X,
  Eye,
  CheckSquare,
  Square,
  Sparkles,
  Plus,
} from 'lucide-react';

interface DocumentExplorerProps {
  initialTarget?: TargetChunkLink | null;
  onClearTarget?: () => void;
  onNavigateToSearch?: () => void;
  appendTargetTestSet?: { id: string; name: string } | null;
  onClearAppendTarget?: () => void;
  onTestSetCreated?: (testsetId: string) => void;
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
    case 'json':
      return (
        <span className="px-1.5 py-0.2 text-[9px] font-mono font-bold text-amber-700 bg-amber-50 border border-amber-200 rounded shrink-0">
          JSON
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
  appendTargetTestSet,
  onClearAppendTarget,
  onTestSetCreated,
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
  const [viewingFullContent, setViewingFullContent] = useState(false);
  const [fullContentText, setFullContentText] = useState<string | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);
  const [selectedChunkIndices, setSelectedChunkIndices] = useState<Set<number>>(new Set());
  const [activeChunkTarget, setActiveChunkTarget] = useState<TargetChunkLink | null>(
    initialTarget || null
  );

  // TestSet Creation Modal State
  const [isCreateTestSetModalOpen, setIsCreateTestSetModalOpen] = useState(false);
  const [testSetModalMode, setTestSetModalMode] = useState<'create_new' | 'add_to_existing'>('create_new');
  const [existingTestSets, setExistingTestSets] = useState<TestSet[]>([]);
  const [selectedExistingTestSetId, setSelectedExistingTestSetId] = useState('');
  const [testSetName, setTestSetName] = useState('');
  const [creatingTestSet, setCreatingTestSet] = useState(false);

  // Track chunks already present in testsets to strictly prevent duplicates
  const [targetTestSetExistingCoords, setTargetTestSetExistingCoords] = useState<Set<string>>(new Set());
  const [modalTestSetExistingCoords, setModalTestSetExistingCoords] = useState<Set<string>>(new Set());

  // Load coordinates of target testset when in append mode
  useEffect(() => {
    if (appendTargetTestSet?.id) {
      const loadExistingCoords = async () => {
        try {
          const detail = await api.getTestSet(appendTargetTestSet.id);
          const coords = new Set<string>();
          for (const item of detail.items || []) {
            coords.add(`${item.answer_document_id}:${item.answer_chunk_index}`);
          }
          setTargetTestSetExistingCoords(coords);
        } catch {
          setTargetTestSetExistingCoords(new Set());
        }
      };
      loadExistingCoords();
    } else {
      setTargetTestSetExistingCoords(new Set());
    }
  }, [appendTargetTestSet]);

  // Load coordinates of selected testset in modal when in 'add_to_existing' mode
  useEffect(() => {
    if (isCreateTestSetModalOpen && testSetModalMode === 'add_to_existing' && selectedExistingTestSetId) {
      const loadCoords = async () => {
        try {
          const detail = await api.getTestSet(selectedExistingTestSetId);
          const coords = new Set<string>();
          for (const item of detail.items || []) {
            coords.add(`${item.answer_document_id}:${item.answer_chunk_index}`);
          }
          setModalTestSetExistingCoords(coords);
        } catch {
          setModalTestSetExistingCoords(new Set());
        }
      };
      loadCoords();
    } else {
      setModalTestSetExistingCoords(new Set());
    }
  }, [isCreateTestSetModalOpen, testSetModalMode, selectedExistingTestSetId]);

  const { addToast } = useToast();
  const pollingRef = useRef<number | null>(null);
  const selectedDocRef = useRef<DocumentItem | null>(selectedDoc);
  const chunkRefs = useRef<Record<number, HTMLDivElement | null>>({});

  useEffect(() => {
    selectedDocRef.current = selectedDoc;
  }, [selectedDoc]);

  const fetchChunksForDoc = useCallback(async (docId: string, silent = false) => {
    if (!silent) {
      setLoadingChunks(true);
      setSelectedChunkIndices(new Set());
    }
    try {
      const res = await api.getDocumentChunks(docId);
      setDocChunks(res.chunks || []);
    } catch {
      setDocChunks(null);
    } finally {
      if (!silent) {
        setLoadingChunks(false);
      }
    }
  }, []);

  const selectDocumentById = useCallback(
    async (docId: string) => {
      try {
        const doc = await api.getDocument(docId);
        setSelectedDoc(doc);
        if (doc.status !== 'pending') {
          fetchChunksForDoc(doc.id);
        }
      } catch (err) {
        addToast('error', '加载文档失败', formatErrorMessage(err));
      }
    },
    [fetchChunksForDoc, addToast]
  );

  const fetchDocuments = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        const res = await api.listDocuments(page, pageSize);
        setDocuments(res.items || []);
        setTotal(res.total || 0);

        const currentSelected = selectedDocRef.current;
        if (currentSelected) {
          const updated = (res.items || []).find((d) => d.id === currentSelected.id);
          if (updated) {
            const wasPending = currentSelected.status === 'pending';
            setSelectedDoc(updated);
            if (wasPending && updated.status === 'success') {
              fetchChunksForDoc(updated.id);
            }
          }
        } else if ((res.items || []).length > 0) {
          setSelectedDoc(res.items[0]);
          if (res.items[0].status !== 'pending') {
            fetchChunksForDoc(res.items[0].id);
          }
        }
      } catch (err) {
        if (!silent) {
          addToast('error', '获取文档列表失败', formatErrorMessage(err));
        }
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [page, pageSize, fetchChunksForDoc, addToast]
  );

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments, refreshTrigger]);

  // When initialTarget arrives
  useEffect(() => {
    if (initialTarget && initialTarget.documentId) {
      setActiveChunkTarget(initialTarget);
      selectDocumentById(initialTarget.documentId);
    } else if (!initialTarget) {
      setActiveChunkTarget(null);
    }
  }, [initialTarget, selectDocumentById]);

  // Auto scroll to target chunk if specified
  useEffect(() => {
    if (activeChunkTarget?.chunkIndex !== undefined && docChunks && docChunks.length > 0) {
      const idx = activeChunkTarget.chunkIndex;
      const el = chunkRefs.current[idx];
      if (el) {
        setTimeout(() => {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 100);
      }
    }
  }, [activeChunkTarget, docChunks]);

  // Real-time Auto-refresh without flickering
  useEffect(() => {
    if (autoRefresh) {
      pollingRef.current = window.setInterval(() => {
        const currentDoc = selectedDocRef.current;
        const hasPending =
          documents.some((d) => d.status === 'pending') || currentDoc?.status === 'pending';
        if (hasPending) {
          fetchDocuments(true);
        }
      }, 3000);
    }
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [autoRefresh, documents, fetchDocuments]);

  const handleSelectDoc = (doc: DocumentItem) => {
    setSelectedDoc(doc);
    setActiveChunkTarget(null);
    if (onClearTarget) onClearTarget();
    setDocChunks(null);
    setChunkFilterTerm('');
    setSelectedChunkIndices(new Set());
    fetchChunksForDoc(doc.id);
    window.location.hash = `#/documents/${doc.id}`;
  };

  const handleCopy = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(key);
    setTimeout(() => setCopiedId(null), 2000);
    addToast('info', '已复制到剪贴板');
  };

  const handleCopyChunkText = (text: string, idx: number) => {
    navigator.clipboard.writeText(text);
    setCopiedChunkIdx(idx);
    setTimeout(() => setCopiedChunkIdx(null), 2000);
    addToast('info', `已复制切片 #${idx + 1} 原文`);
  };

  const handleDeleteDoc = async (doc: DocumentItem) => {
    if (!window.confirm(`确定要删除文档「${doc.name}」及其在 Qdrant 向量库中的所有切片吗？`)) {
      return;
    }
    setDeleting(true);
    try {
      await api.deleteDocument(doc.id);
      addToast('success', '删除成功', `文档「${doc.name}」已彻底清除`);
      setSelectedDoc(null);
      setDocChunks(null);
      setSelectedChunkIndices(new Set());
      if (onClearTarget) onClearTarget();
      fetchDocuments();
    } catch (err) {
      addToast('error', '删除失败', formatErrorMessage(err));
    } finally {
      setDeleting(false);
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

  // Chunk Selection Logic
  const toggleChunkSelection = (chunkIdx: number) => {
    if (
      selectedDoc &&
      appendTargetTestSet?.id &&
      targetTestSetExistingCoords.has(`${selectedDoc.id}:${chunkIdx}`)
    ) {
      addToast('info', '该切片已在评测集中', `切片 #${chunkIdx + 1} 已经在该评测集中，无法重复出题`);
      return;
    }
    setSelectedChunkIndices((prev) => {
      const next = new Set(prev);
      if (next.has(chunkIdx)) {
        next.delete(chunkIdx);
      } else {
        next.add(chunkIdx);
      }
      return next;
    });
  };

  const selectAllChunks = () => {
    if (!docChunks || !selectedDoc) return;
    const isAppendMode = Boolean(appendTargetTestSet?.id);
    const available = docChunks
      .filter((c) => !isAppendMode || !targetTestSetExistingCoords.has(`${selectedDoc.id}:${c.chunk_index}`))
      .map((c) => c.chunk_index);

    setSelectedChunkIndices(new Set(available));

    if (isAppendMode && available.length < docChunks.length) {
      const skipped = docChunks.length - available.length;
      addToast('info', `已选中 ${available.length} 个未添加切片`, `已自动排除 ${skipped} 个已存在的切片`);
    } else {
      addToast('info', `已选中当前全部 ${available.length} 个切片`);
    }
  };

  const clearSelectedChunks = () => {
    setSelectedChunkIndices(new Set());
  };

  const handleOpenCreateTestSetModal = async () => {
    if (!selectedDoc || selectedChunkIndices.size === 0) return;
    setTestSetName(`${selectedDoc.name.replace(/\.[^/.]+$/, '')} 评测集 (${selectedChunkIndices.size} 题)`);
    setIsCreateTestSetModalOpen(true);

    try {
      const list = await api.listTestSets();
      setExistingTestSets(list);
      if (list.length > 0) {
        setSelectedExistingTestSetId(list[0].id);
      }
    } catch {
      setExistingTestSets([]);
    }
  };

  const handleDirectAppend = async () => {
    if (!selectedDoc || selectedChunkIndices.size === 0 || !appendTargetTestSet) return;

    // Strict deduplication against existing testset coordinates
    const filteredIndices = Array.from(selectedChunkIndices)
      .sort((a, b) => a - b)
      .filter((idx) => !targetTestSetExistingCoords.has(`${selectedDoc.id}:${idx}`));

    if (filteredIndices.length === 0) {
      addToast('warning', '无需重复添加', '所勾选的切片已全部存在于该评测集中，无法重复出题');
      return;
    }

    setCreatingTestSet(true);
    const chunks = filteredIndices.map((idx) => ({
      document_id: selectedDoc.id,
      chunk_index: idx,
    }));

    try {
      const res = await api.addItemsToTestSet(appendTargetTestSet.id, chunks);
      addToast(
        'success',
        '切片已成功追加！',
        `已向评测集「${res.name}」追加 ${chunks.length} 个新切片出题任务`
      );
      setSelectedChunkIndices(new Set());
      const targetId = appendTargetTestSet.id;
      if (onClearAppendTarget) onClearAppendTarget();
      if (onTestSetCreated) {
        onTestSetCreated(targetId);
      }
    } catch (err) {
      addToast('error', '追加切片失败', formatErrorMessage(err));
    } finally {
      setCreatingTestSet(false);
    }
  };

  const handleConfirmCreateTestSet = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedDoc || selectedChunkIndices.size === 0) return;

    setCreatingTestSet(true);
    const sortedIndices = Array.from(selectedChunkIndices).sort((a, b) => a - b);

    try {
      let res: TestSet;
      if (testSetModalMode === 'create_new') {
        const chunks = sortedIndices.map((idx) => ({
          document_id: selectedDoc.id,
          chunk_index: idx,
        }));
        res = await api.createTestSetWithChunks(testSetName.trim() || undefined, chunks);
        addToast(
          'success',
          '评测集创建成功！',
          `评测集「${res.name}」已提交，后台 LLM Worker 将异步为 ${chunks.length} 个切片出题`
        );
      } else {
        if (!selectedExistingTestSetId) {
          addToast('warning', '请选择目标评测集');
          setCreatingTestSet(false);
          return;
        }

        // Strict deduplication for modal append mode
        const filteredIndices = sortedIndices.filter(
          (idx) => !modalTestSetExistingCoords.has(`${selectedDoc.id}:${idx}`)
        );

        if (filteredIndices.length === 0) {
          addToast('warning', '无需重复添加', '所勾选的切片已全部存在于目标评测集中，无法重复出题');
          setCreatingTestSet(false);
          return;
        }

        const chunks = filteredIndices.map((idx) => ({
          document_id: selectedDoc.id,
          chunk_index: idx,
        }));

        res = await api.addItemsToTestSet(selectedExistingTestSetId, chunks);
        addToast(
          'success',
          '切片已追加至评测集！',
          `已向评测集「${res.name}」追加 ${chunks.length} 个新切片出题任务（已过滤重复）`
        );
      }

      setIsCreateTestSetModalOpen(false);
      setSelectedChunkIndices(new Set());

      if (onTestSetCreated) {
        onTestSetCreated(res.id);
      }
    } catch (err) {
      addToast('error', '提交评测集失败', formatErrorMessage(err));
    } finally {
      setCreatingTestSet(false);
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
            INDEXING
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

  const filteredDocuments = documents.filter((doc) => {
    const matchesSearch = doc.name.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesStatus = statusFilter === 'all' || doc.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const filteredChunks = (docChunks || []).filter((chunk) => {
    if (!chunkFilterTerm.trim()) return true;
    return chunk.text.toLowerCase().includes(chunkFilterTerm.toLowerCase());
  });

  const totalPages = Math.ceil(total / pageSize) || 1;

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-slate-50 overflow-hidden relative">
      {/* Append Mode Banner */}
      {appendTargetTestSet && (
        <div className="bg-blue-600 text-white px-5 py-2.5 flex items-center justify-between text-xs font-mono shadow-sm z-20 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <Sparkles className="w-4 h-4 text-amber-300 animate-pulse shrink-0" />
            <span className="truncate">
              <strong>追加切片模式：</strong>正在为评测集「<strong className="text-amber-200 underline">{appendTargetTestSet.name}</strong>」挑选切片。勾选切片后，点击下方浮动条直接确认追加。
            </span>
          </div>
          <button
            onClick={() => {
              if (onClearAppendTarget) onClearAppendTarget();
              clearSelectedChunks();
            }}
            className="px-2.5 py-1 rounded bg-blue-700 hover:bg-blue-800 text-white text-[11px] transition-colors cursor-pointer shrink-0 ml-2"
          >
            退出追加模式
          </button>
        </div>
      )}

      {/* Main split pane */}
      <div className="flex-1 flex flex-col md:flex-row min-h-0 overflow-hidden relative">
        {/* Left Master Pane: Document Collection Table */}
        <div className="w-full md:w-5/12 lg:w-4/12 border-r border-slate-200 flex flex-col bg-white min-h-0">
        {/* Top filter / search bar */}
        <div className="p-3.5 border-b border-slate-200 space-y-2.5 bg-slate-50/70">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5 font-mono font-bold text-slate-800">
              <Layers className="w-3.5 h-3.5 text-blue-600" />
              <span>知识库文档 ({total})</span>
            </div>

            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1 text-[11px] font-mono text-slate-500 cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoRefresh}
                  onChange={(e) => setAutoRefresh(e.target.checked)}
                  className="rounded bg-white border-slate-300 text-blue-600 w-3 h-3"
                />
                <span>自动轮询</span>
              </label>

              <button
                onClick={() => fetchDocuments(false)}
                disabled={loading}
                className="p-1 rounded bg-white hover:bg-slate-100 border border-slate-200 text-slate-500 hover:text-slate-800 transition-colors cursor-pointer"
                title="刷新文档列表"
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
                placeholder="按文档名称过滤..."
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
              <option value="all">全部状态</option>
              <option value="success">SUCCESS</option>
              <option value="pending">PENDING</option>
              <option value="failed">FAILED</option>
            </select>
          </div>
        </div>

        {/* Document items list */}
        <div className="flex-1 overflow-y-auto divide-y divide-slate-100">
          {loading && documents.length === 0 ? (
            <div className="p-8 text-center text-slate-400 font-mono text-xs">
              <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-blue-600" />
              正在加载文档列表...
            </div>
          ) : filteredDocuments.length === 0 ? (
            <div className="p-8 text-center text-slate-400 font-mono text-xs">
              暂无匹配的文档记录
            </div>
          ) : (
            filteredDocuments.map((doc) => {
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
                      <FileText
                        className={`w-4 h-4 shrink-0 ${
                          isSelected ? 'text-blue-600' : 'text-slate-400'
                        }`}
                      />
                      {getFileFormatBadge(doc.name)}
                      <span className="text-xs font-mono text-slate-900 font-medium truncate">
                        {doc.name}
                      </span>
                    </div>
                    {getStatusBadge(doc.status)}
                  </div>

                  <div className="flex items-center justify-between gap-2 mt-2 text-[11px] font-mono text-slate-500">
                    <span className="flex items-center gap-1">
                      <Binary className="w-3 h-3 text-blue-600" />
                      <span>{doc.chunk_count || 0} 个切片</span>
                    </span>
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
        <div className="p-2.5 border-t border-slate-200 bg-slate-50 flex items-center justify-between text-[11px] font-mono text-slate-500">
          <span>
            第 {page} / {totalPages} 页
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="p-1 rounded bg-white border border-slate-200 disabled:opacity-30 hover:bg-slate-100 cursor-pointer"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="p-1 rounded bg-white border border-slate-200 disabled:opacity-30 hover:bg-slate-100 cursor-pointer"
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Right Detail Pane: Document & Chunk Inspector */}
      <div className="flex-1 flex flex-col bg-slate-50 overflow-y-auto p-6 space-y-4 pb-24">
        {selectedDoc ? (
          <div className="max-w-5xl space-y-4">
            {/* Back to search banner if navigated from search */}
            {activeChunkTarget && activeChunkTarget.chunkIndex !== undefined && onNavigateToSearch && (
              <div className="flex items-center justify-between p-3.5 bg-blue-50 border border-blue-200 rounded-xl text-xs font-mono text-blue-800 shadow-2xs">
                <div className="flex items-center gap-2">
                  <Target className="w-4 h-4 text-blue-600 shrink-0" />
                  <span>
                    已定位至检索切片目标: <strong>{selectedDoc.name}</strong> (切片 #{activeChunkTarget.chunkIndex + 1})
                  </span>
                </div>
                <button
                  onClick={onNavigateToSearch}
                  className="flex items-center gap-1.5 px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-semibold transition-colors cursor-pointer"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  <span>返回检索控制台</span>
                </button>
              </div>
            )}

            {/* Document Header Specs Card */}
            <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-4 shadow-xs">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <FileText className="w-5 h-5 text-blue-600 shrink-0" />
                    {getFileFormatBadge(selectedDoc.name)}
                    <h2 className="text-base font-bold font-mono text-slate-900 break-all">
                      {selectedDoc.name}
                    </h2>
                  </div>
                  <div className="flex items-center gap-2 text-xs font-mono text-slate-500">
                    <span>UUID: {selectedDoc.id}</span>
                    <button
                      onClick={() => handleCopy(selectedDoc.id, 'docId')}
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

                  {/* View Full Content Button */}
                  <button
                    onClick={() => handleViewFullContent(selectedDoc.id)}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs font-mono text-slate-700 hover:text-slate-900 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-md transition-colors cursor-pointer"
                    title="查看原始全文"
                  >
                    <Eye className="w-3.5 h-3.5 text-slate-500" />
                    <span>查看全文</span>
                  </button>

                  {/* Download Raw File Button */}
                  <a
                    href={api.getDownloadUrl(selectedDoc.id)}
                    target="_blank"
                    rel="noreferrer"
                    download={selectedDoc.name}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs font-mono text-slate-700 hover:text-slate-900 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-md transition-colors cursor-pointer"
                    title="下载原始文件"
                  >
                    <Download className="w-3.5 h-3.5 text-slate-500" />
                    <span>下载原文</span>
                  </a>

                  {/* Delete Document Button */}
                  <button
                    onClick={() => handleDeleteDoc(selectedDoc)}
                    disabled={deleting}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs font-mono text-rose-600 hover:text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 rounded-md transition-colors cursor-pointer disabled:opacity-50"
                    title="删除该文档及其全部向量点"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>{deleting ? '删除中...' : '删除文档'}</span>
                  </button>
                </div>
              </div>

              {/* Error Message banner if failed */}
              {selectedDoc.error_message && (
                <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-xs font-mono text-rose-700 flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0 text-rose-600 mt-0.5" />
                  <div>
                    <span className="font-bold">失败原因:</span> {selectedDoc.error_message}
                  </div>
                </div>
              )}

              {/* Specs Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-3 border-t border-slate-100 text-xs font-mono">
                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <span className="text-slate-500 text-[10px] block mb-0.5">切片总数 (CHUNKS)</span>
                  <span className="text-blue-700 font-bold text-base">
                    {selectedDoc.chunk_count || (docChunks ? docChunks.length : 0)}
                  </span>
                </div>

                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <span className="text-slate-500 text-[10px] block mb-0.5">向量维度 (DENSE)</span>
                  <span className="text-slate-800 font-bold text-base">1024-dim</span>
                </div>

                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <span className="text-slate-500 text-[10px] block mb-0.5">创建时间</span>
                  <span className="text-slate-700 text-[11px] truncate block">
                    {selectedDoc.created_at
                      ? new Date(selectedDoc.created_at).toLocaleString('zh-CN')
                      : '—'}
                  </span>
                </div>

                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <span className="text-slate-500 text-[10px] block mb-0.5">索引完成时间</span>
                  <span className="text-slate-700 text-[11px] truncate block">
                    {selectedDoc.indexed_at
                      ? new Date(selectedDoc.indexed_at).toLocaleString('zh-CN')
                      : '—'}
                  </span>
                </div>
              </div>
            </div>

            {/* Document All Chunks List / Text Viewer */}
            <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-4 shadow-xs">
              <div className="flex flex-wrap items-center justify-between gap-2.5 text-xs font-mono">
                <div className="flex items-center gap-2 text-slate-900 font-bold">
                  <Cpu className="w-4 h-4 text-blue-600" />
                  <span>
                    切片全量列表 ({docChunks ? docChunks.length : selectedDoc.chunk_count || 0} 个切片)
                  </span>
                </div>

                {/* Batch selection buttons & search box */}
                <div className="flex items-center gap-2 flex-wrap">
                  {docChunks && docChunks.length > 0 && (
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={selectAllChunks}
                        className="px-2 py-1 text-[11px] rounded bg-slate-100 hover:bg-slate-200 border border-slate-200 text-slate-700 transition-colors cursor-pointer"
                      >
                        全选
                      </button>
                      {selectedChunkIndices.size > 0 && (
                        <button
                          onClick={clearSelectedChunks}
                          className="px-2 py-1 text-[11px] rounded bg-slate-100 hover:bg-slate-200 border border-slate-200 text-slate-700 transition-colors cursor-pointer"
                        >
                          清空已选 ({selectedChunkIndices.size})
                        </button>
                      )}
                    </div>
                  )}

                  {docChunks && docChunks.length > 0 && (
                    <div className="relative">
                      <Search className="w-3 h-3 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
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
                  正在从 Qdrant 向量库加载全部切片文本...
                </div>
              ) : filteredChunks.length > 0 ? (
                <div className="space-y-3">
                  {filteredChunks.map((chunk) => {
                    const isFocused = activeChunkTarget?.chunkIndex === chunk.chunk_index;
                    const isSelected = selectedChunkIndices.has(chunk.chunk_index);
                    const lineCount = chunk.text.split('\n').length;
                    const isAlreadyInTarget = Boolean(
                      selectedDoc &&
                      appendTargetTestSet?.id &&
                      targetTestSetExistingCoords.has(`${selectedDoc.id}:${chunk.chunk_index}`)
                    );

                    return (
                      <div
                        key={chunk.chunk_index}
                        ref={(el) => {
                          chunkRefs.current[chunk.chunk_index] = el;
                        }}
                        className={`p-4 rounded-xl border transition-all ${
                          isAlreadyInTarget
                            ? 'bg-slate-100/70 border-slate-200 opacity-80'
                            : isSelected
                            ? 'bg-blue-50/50 border-blue-400 ring-1 ring-blue-300'
                            : isFocused
                            ? 'bg-blue-50/70 border-2 border-blue-600 shadow-md'
                            : 'bg-slate-50/70 border-slate-200 hover:border-slate-300'
                        }`}
                      >
                        {/* Chunk Header */}
                        <div className="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-slate-200/80 text-xs font-mono">
                          <div className="flex items-center gap-2">
                            {/* Checkbox for Eval Selection */}
                            <button
                              type="button"
                              disabled={isAlreadyInTarget}
                              onClick={() => toggleChunkSelection(chunk.chunk_index)}
                              className={`transition-colors ${
                                isAlreadyInTarget
                                  ? 'cursor-not-allowed text-emerald-600'
                                  : 'text-slate-400 hover:text-blue-600 cursor-pointer'
                              }`}
                              title={
                                isAlreadyInTarget
                                  ? '该切片已在目标评测集中，不可重复出题'
                                  : isSelected
                                  ? '取消勾选该切片'
                                  : '勾选该切片参与出题评测'
                              }
                            >
                              {isAlreadyInTarget ? (
                                <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                              ) : isSelected ? (
                                <CheckSquare className="w-4 h-4 text-blue-600" />
                              ) : (
                                <Square className="w-4 h-4 text-slate-300 hover:text-slate-500" />
                              )}
                            </button>

                            <span
                              className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                                isAlreadyInTarget
                                  ? 'bg-slate-200 text-slate-600'
                                  : isFocused
                                  ? 'bg-blue-600 text-white'
                                  : isSelected
                                  ? 'bg-blue-100 text-blue-800 border border-blue-200'
                                  : 'bg-white border border-slate-200 text-slate-800'
                              }`}
                            >
                              Chunk #{chunk.chunk_index + 1}
                            </span>

                            {isAlreadyInTarget && (
                              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                                <Check className="w-3 h-3 text-emerald-600" />
                                <span>已在目标评测集中</span>
                              </span>
                            )}

                            {chunk.point_id && (
                              <span className="text-[10px] text-slate-400">
                                Point ID: {chunk.point_id.substring(0, 12)}...
                              </span>
                            )}
                          </div>

                          <div className="flex items-center gap-2">
                            <span className="text-[11px] text-slate-400">
                              {chunk.text.length} 字符 • {lineCount} 行
                            </span>

                            <button
                              onClick={() => handleCopyChunkText(chunk.text, chunk.chunk_index)}
                              className="flex items-center gap-1 px-2 py-0.5 rounded bg-white hover:bg-slate-100 border border-slate-200 text-slate-600 hover:text-slate-900 text-[11px] transition-colors cursor-pointer"
                              title="复制该切片文本"
                            >
                              {copiedChunkIdx === chunk.chunk_index ? (
                                <Check className="w-3 h-3 text-emerald-600" />
                              ) : (
                                <Copy className="w-3.5 h-3.5 text-slate-400" />
                              )}
                              <span>{copiedChunkIdx === chunk.chunk_index ? '已复制' : '复制'}</span>
                            </button>
                          </div>
                        </div>

                        {/* Chunk Content Text */}
                        <div className="mt-3 text-xs font-mono text-slate-900 whitespace-pre-wrap leading-relaxed">
                          {chunk.text}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="p-8 text-center text-slate-400 font-mono text-xs">
                  未匹配到符合条件的切片
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center p-16 text-slate-400 font-mono text-xs space-y-2">
            <FileText className="w-8 h-8 text-slate-400" />
            <p>请在左侧列表中选择一篇文档查看其切片详情</p>
          </div>
        )}
      </div>
      </div>

      {/* Floating Bottom Bar when chunks are selected */}
      {selectedChunkIndices.size > 0 && selectedDoc && (
        <div className="absolute bottom-5 left-1/2 -translate-x-1/2 z-30 bg-slate-900/95 text-white backdrop-blur-md px-5 py-3 rounded-2xl shadow-2xl border border-slate-700 flex items-center gap-4 animate-in fade-in slide-in-from-bottom-3 duration-200">
          <div className="flex items-center gap-2 font-mono text-xs">
            <CheckSquare className="w-4 h-4 text-blue-400" />
            <span>
              已选中 <strong className="text-blue-300 text-sm">{selectedChunkIndices.size}</strong> 个切片
            </span>
          </div>

          <div className="h-4 w-px bg-slate-700" />

          {appendTargetTestSet ? (
            <button
              onClick={handleDirectAppend}
              disabled={creatingTestSet}
              className="flex items-center gap-1.5 px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white rounded-xl text-xs font-semibold font-mono shadow-md transition-all cursor-pointer"
            >
              {creatingTestSet ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  <span>正在追加切片 (POST /items)...</span>
                </>
              ) : (
                <>
                  <Plus className="w-3.5 h-3.5" />
                  <span>确认追加至「{appendTargetTestSet.name}」➔</span>
                </>
              )}
            </button>
          ) : (
            <button
              onClick={handleOpenCreateTestSetModal}
              className="flex items-center gap-1.5 px-4 py-1.5 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white rounded-xl text-xs font-semibold font-mono shadow-md transition-all cursor-pointer"
            >
              <Sparkles className="w-3.5 h-3.5 text-amber-300" />
              <span>加入 / 创建评测集 ➔</span>
            </button>
          )}

          <button
            onClick={clearSelectedChunks}
            className="text-slate-400 hover:text-slate-200 text-xs font-mono transition-colors cursor-pointer"
          >
            取消
          </button>
        </div>
      )}

      {/* Create TestSet Modal */}
      {isCreateTestSetModalOpen && selectedDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-blue-600" />
                <h3 className="text-sm font-bold text-slate-900 font-mono">
                  {testSetModalMode === 'create_new' ? '创建切片评测集' : '追加切片至评测集'}
                </h3>
              </div>
              <button
                onClick={() => setIsCreateTestSetModalOpen(false)}
                className="text-slate-400 hover:text-slate-700 p-1 rounded-lg cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {existingTestSets.length > 0 && (
              <div className="flex border-b border-slate-200 text-xs font-mono">
                <button
                  type="button"
                  onClick={() => setTestSetModalMode('create_new')}
                  className={`flex-1 py-2 font-medium border-b-2 transition-colors cursor-pointer ${
                    testSetModalMode === 'create_new'
                      ? 'border-blue-600 text-blue-600 font-bold'
                      : 'border-transparent text-slate-500 hover:text-slate-700'
                  }`}
                >
                  新建评测集并添加
                </button>
                <button
                  type="button"
                  onClick={() => setTestSetModalMode('add_to_existing')}
                  className={`flex-1 py-2 font-medium border-b-2 transition-colors cursor-pointer ${
                    testSetModalMode === 'add_to_existing'
                      ? 'border-blue-600 text-blue-600 font-bold'
                      : 'border-transparent text-slate-500 hover:text-slate-700'
                  }`}
                >
                  追加到已有评测集 ({existingTestSets.length})
                </button>
              </div>
            )}

            <form onSubmit={handleConfirmCreateTestSet} className="space-y-4 text-xs font-mono">
              <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl space-y-1.5 text-slate-700">
                <div className="flex items-center justify-between">
                  <span>源文档:</span>
                  <strong className="text-slate-900">{selectedDoc.name}</strong>
                </div>
                <div className="flex items-center justify-between">
                  <span>勾选切片数量:</span>
                  <span className="font-bold text-blue-700">{selectedChunkIndices.size} 块</span>
                </div>
                <div className="flex flex-wrap gap-1 pt-1">
                  {Array.from(selectedChunkIndices)
                    .sort((a, b) => a - b)
                    .map((idx) => (
                      <span
                        key={idx}
                        className="px-1.5 py-0.5 rounded bg-blue-100 text-blue-800 text-[10px] font-bold"
                      >
                        #{idx + 1}
                      </span>
                    ))}
                </div>
              </div>

              {testSetModalMode === 'create_new' ? (
                <div className="space-y-1.5">
                  <label className="text-slate-700 font-medium block">
                    评测集名称 (可选)
                  </label>
                  <input
                    type="text"
                    value={testSetName}
                    onChange={(e) => setTestSetName(e.target.value)}
                    placeholder="例如：系统核心设计评测集"
                    className="w-full p-2.5 bg-slate-50 border border-slate-300 rounded-lg text-slate-900 focus:outline-none focus:border-blue-600 focus:bg-white"
                  />
                </div>
              ) : (
                <div className="space-y-2">
                  <div className="space-y-1.5">
                    <label className="text-slate-700 font-medium block">
                      选择目标评测集*
                    </label>
                    <select
                      value={selectedExistingTestSetId}
                      onChange={(e) => setSelectedExistingTestSetId(e.target.value)}
                      className="w-full p-2.5 bg-slate-50 border border-slate-300 rounded-lg text-slate-900 focus:outline-none focus:border-blue-600 focus:bg-white cursor-pointer"
                    >
                      {existingTestSets.map((ts) => (
                        <option key={ts.id} value={ts.id}>
                          {ts.name} (已有 {ts.progress_total} 题，{ts.status})
                        </option>
                      ))}
                    </select>
                  </div>

                  {selectedDoc && selectedExistingTestSetId && (
                    <div className="p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-[11px] font-mono text-slate-600 space-y-1">
                      {(() => {
                        const totalSelected = selectedChunkIndices.size;
                        const dupes = Array.from(selectedChunkIndices).filter((idx) =>
                          modalTestSetExistingCoords.has(`${selectedDoc.id}:${idx}`)
                        ).length;
                        const newCount = totalSelected - dupes;
                        return (
                          <>
                            <div className="flex items-center justify-between text-slate-700">
                              <span>当前勾选切片:</span>
                              <strong>{totalSelected} 块</strong>
                            </div>
                            <div className="flex items-center justify-between text-emerald-700 font-semibold">
                              <span>• 预计新增出题:</span>
                              <span>{newCount} 块</span>
                            </div>
                            {dupes > 0 && (
                              <div className="flex items-center justify-between text-amber-700 font-medium">
                                <span>• 已存在切片 (将自动去重):</span>
                                <span>{dupes} 块</span>
                              </div>
                            )}
                          </>
                        );
                      })()}
                    </div>
                  )}
                </div>
              )}

              <div className="p-3 bg-amber-50/70 border border-amber-200 rounded-lg text-[11px] text-amber-900 leading-relaxed">
                💡 提交后系统将在后台异步挂载出题任务，由 LLM Worker 基于每个选中的切片自动生成自然语言提问。
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setIsCreateTestSetModalOpen(false)}
                  className="px-3 py-1.5 text-slate-600 hover:bg-slate-100 rounded-lg cursor-pointer"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={creatingTestSet}
                  className="flex items-center gap-1.5 px-4 py-1.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white font-semibold rounded-lg shadow-xs disabled:opacity-50 cursor-pointer"
                >
                  {creatingTestSet ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>正在提交任务...</span>
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-3.5 h-3.5" />
                      <span>
                        {testSetModalMode === 'create_new'
                          ? '确认创建 (POST /eval/testsets)'
                          : '确认追加 (POST /items)'}
                      </span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Full Content Preview Modal */}
      {viewingFullContent && selectedDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-3xl w-full p-6 shadow-2xl flex flex-col max-h-[85vh] space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <FileCode className="w-5 h-5 text-blue-600" />
                <h3 className="text-sm font-bold text-slate-900 font-mono truncate max-w-md">
                  {selectedDoc.name} - 原始全文
                </h3>
              </div>
              <button
                onClick={() => setViewingFullContent(false)}
                className="text-slate-400 hover:text-slate-700 p-1 rounded-lg hover:bg-slate-100 cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 bg-slate-50 border border-slate-200 rounded-xl">
              {loadingContent ? (
                <div className="p-8 text-center text-slate-400 font-mono text-xs">
                  <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-blue-600" />
                  正在读取文件原文...
                </div>
              ) : (
                <pre className="text-xs font-mono text-slate-800 whitespace-pre-wrap leading-relaxed">
                  {fullContentText}
                </pre>
              )}
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-slate-100">
              <span className="text-xs font-mono text-slate-500">
                {fullContentText ? `${fullContentText.length} 字符` : ''}
              </span>
              <button
                onClick={() => setViewingFullContent(false)}
                className="px-4 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded-lg cursor-pointer"
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
