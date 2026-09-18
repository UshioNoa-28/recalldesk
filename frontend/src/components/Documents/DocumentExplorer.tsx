import React, { useState, useEffect, useCallback, useRef } from 'react';
import { DocumentItem, DocumentStatus, TargetChunkLink, TestSet, SelectedChunkInfo } from '../../types';
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
  RotateCw,
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
  const [confirmDeleteDoc, setConfirmDeleteDoc] = useState<DocumentItem | null>(null);
  const [reindexingDocId, setReindexingDocId] = useState<string | null>(null);
  const [rerunningGraphDocId, setRerunningGraphDocId] = useState<string | null>(null);
  const [viewingFullContent, setViewingFullContent] = useState(false);
  const [fullContentText, setFullContentText] = useState<string | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);
  const [selectedChunks, setSelectedChunks] = useState<SelectedChunkInfo[]>([]);
  const [itemMode, setItemMode] = useState<'single' | 'multi'>('single');
  const [showSelectedDrawer, setShowSelectedDrawer] = useState(false);
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
  const isSubmittingRef = useRef<boolean>(false);

  // Track chunks already present in testsets (for visual hints)
  const [targetTestSetExistingCoords, setTargetTestSetExistingCoords] = useState<Set<string>>(new Set());

  // Load coordinates of target testset when in append mode
  useEffect(() => {
    if (appendTargetTestSet?.id) {
      const loadExistingCoords = async () => {
        try {
          const detail = await api.getTestSet(appendTargetTestSet.id);
          const coords = new Set<string>();
          for (const item of detail.items || []) {
            for (const ref of item.evidence || []) {
              coords.add(`${ref.document_id}:${ref.chunk_index}`);
            }
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

  const requestedDocIdRef = useRef<string | null>(null);

  const selectDocumentById = useCallback(
    async (docId: string) => {
      if (!docId) return;
      if (requestedDocIdRef.current === docId) return;
      requestedDocIdRef.current = docId;

      try {
        const doc = await api.getDocument(docId);
        setSelectedDoc(doc);
        if (doc.status !== 'pending') {
          fetchChunksForDoc(doc.id);
        }
      } catch (err) {
        addToast('error', '加载文档失败', formatErrorMessage(err));
        if (window.location.hash.startsWith('#/documents/')) {
          window.location.hash = '#/documents';
        }
        if (onClearTarget) onClearTarget();
      } finally {
        setTimeout(() => {
          if (requestedDocIdRef.current === docId) {
            requestedDocIdRef.current = null;
          }
        }, 800);
      }
    },
    [fetchChunksForDoc, addToast, onClearTarget]
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
            const hasChanged =
              currentSelected.status !== updated.status ||
              currentSelected.chunk_count !== updated.chunk_count ||
              currentSelected.error_message !== updated.error_message ||
              currentSelected.graph?.status !== updated.graph?.status ||
              currentSelected.graph?.error !== updated.graph?.error;
            if (hasChanged) {
              setSelectedDoc(updated);
            }
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
  }, [initialTarget?.documentId, initialTarget?.chunkIndex, selectDocumentById]);

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
        const isGraphBusy = (status?: string | null) => status === 'pending' || status === 'queue';
        const hasPending =
          documents.some((d) => d.status === 'pending' || isGraphBusy(d.graph?.status)) ||
          currentDoc?.status === 'pending' ||
          isGraphBusy(currentDoc?.graph?.status);
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
    if (selectedDoc?.id === doc.id) {
      return;
    }
    setSelectedDoc(doc);
    setActiveChunkTarget(null);
    if (onClearTarget) onClearTarget();
    setChunkFilterTerm('');
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

  const executeDeleteDoc = async (doc: DocumentItem) => {
    setDeleting(true);
    try {
      await api.deleteDocument(doc.id);
      addToast('success', '删除成功', `文档「${doc.name}」及其切片已彻底清除`);
      setSelectedDoc(null);
      setDocChunks(null);
      setSelectedChunks((prev) => prev.filter((c) => c.document_id !== doc.id));
      if (onClearTarget) onClearTarget();
      setConfirmDeleteDoc(null);
      window.location.hash = '#/documents';
      fetchDocuments();
    } catch (err) {
      addToast('error', '删除失败', formatErrorMessage(err));
    } finally {
      setDeleting(false);
    }
  };

  const handleReindexDoc = async (documentId: string) => {
    setReindexingDocId(documentId);
    try {
      const res = await api.reindexDocument(documentId);
      addToast('success', '已提交重新索引', `文档「${res.name}」已重新进入解析与分块任务队列`);
      await fetchDocuments(true);
      if (selectedDoc && selectedDoc.id === documentId) {
        try {
          const updated = await api.getDocument(documentId);
          setSelectedDoc(updated);
        } catch {
          setSelectedDoc({ ...selectedDoc, status: 'pending', error_message: null });
        }
      }
    } catch (err) {
      addToast('error', '重新索引失败', formatErrorMessage(err));
    } finally {
      setReindexingDocId(null);
    }
  };

  const handleRerunGraph = async (documentId: string) => {
    setRerunningGraphDocId(documentId);
    try {
      const res = await api.rerunDocumentGraph(documentId);
      addToast(
        'success',
        '图谱抽取已重新入队',
        `《${res.name}》：${res.action === 'requeued' ? '复位重投' : '新建任务'}`
      );
      await fetchDocuments(true);
      if (selectedDoc && selectedDoc.id === documentId) {
        try {
          setSelectedDoc(await api.getDocument(documentId));
        } catch {
          // 列表刷新已触发，详情拉取失败不打扰用户
        }
      }
    } catch (err) {
      addToast('error', '图谱重抽失败', formatErrorMessage(err));
    } finally {
      setRerunningGraphDocId(null);
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

  // Helper to test if a chunk in current document is selected
  const isChunkSelected = (chunkIndex: number) => {
    return Boolean(
      selectedDoc &&
        selectedChunks.some(
          (c) => c.document_id === selectedDoc.id && c.chunk_index === chunkIndex
        )
    );
  };

  // Chunk Selection Logic
  const toggleChunkSelection = (chunk: ChunkItem) => {
    if (!selectedDoc) return;
    const docId = selectedDoc.id;
    const docName = selectedDoc.name;
    const chunkIdx = chunk.chunk_index;

    if (
      appendTargetTestSet?.id &&
      targetTestSetExistingCoords.has(`${docId}:${chunkIdx}`)
    ) {
      addToast('info', '该切片已在评测集中', `切片 #${chunkIdx + 1} 已经在该评测集中，无法重复出题`);
      return;
    }

    setSelectedChunks((prev) => {
      const exists = prev.some(
        (c) => c.document_id === docId && c.chunk_index === chunkIdx
      );
      if (exists) {
        return prev.filter(
          (c) => !(c.document_id === docId && c.chunk_index === chunkIdx)
        );
      }
      return [
        ...prev,
        {
          document_id: docId,
          document_name: docName,
          chunk_index: chunkIdx,
          text: chunk.text,
        },
      ];
    });
  };

  const selectAllChunks = () => {
    if (!docChunks || !selectedDoc) return;
    const docId = selectedDoc.id;
    const docName = selectedDoc.name;

    setSelectedChunks((prev) => {
      const filteredPrev = prev.filter((c) => c.document_id !== docId);
      const newItems: SelectedChunkInfo[] = docChunks.map((c) => ({
        document_id: docId,
        document_name: docName,
        chunk_index: c.chunk_index,
        text: c.text,
      }));
      return [...filteredPrev, ...newItems];
    });

    addToast('info', `已选中当前文档 ${docChunks.length} 个切片`);
  };

  const clearSelectedChunks = () => {
    setSelectedChunks([]);
    setShowSelectedDrawer(false);
  };

  const removeSelectedChunk = (documentId: string, chunkIdx: number) => {
    setSelectedChunks((prev) =>
      prev.filter(
        (c) => !(c.document_id === documentId && c.chunk_index === chunkIdx)
      )
    );
  };

  const handleOpenCreateTestSetModal = async () => {
    if (selectedChunks.length === 0) return;
    const firstDocName = selectedChunks[0].document_name.replace(/\.[^/.]+$/, '');
    const titleSuffix = itemMode === 'multi' ? '多证据评测集' : `评测集 (${selectedChunks.length} 题)`;
    setTestSetName(`${firstDocName} ${titleSuffix}`);
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
    if (selectedChunks.length === 0 || !appendTargetTestSet) return;
    if (isSubmittingRef.current || creatingTestSet) return;

    isSubmittingRef.current = true;
    setCreatingTestSet(true);
    try {
      if (itemMode === 'multi') {
        if (selectedChunks.length > 5) {
          addToast('warning', '超出证据上限', '单道多证据题最多支持 5 块切片');
          return;
        }
        const groupChunks = selectedChunks.map((c) => ({
          document_id: c.document_id,
          chunk_index: c.chunk_index,
        }));
        const res = await api.addItemsToTestSet(appendTargetTestSet.id, {
          groups: [{ chunks: groupChunks }],
        });
        addToast(
          'success',
          '多证据题已成功追加！',
          `已向评测集「${res.name}」追加 1 道多跳/多证据题目（包含 ${groupChunks.length} 块证据切片）`
        );
      } else {
        const chunks = selectedChunks.map((c) => ({
          document_id: c.document_id,
          chunk_index: c.chunk_index,
        }));
        const res = await api.addItemsToTestSet(appendTargetTestSet.id, { chunks });
        addToast(
          'success',
          '切片已成功追加！',
          `已向评测集「${res.name}」追加 ${chunks.length} 个切片出题任务`
        );
      }

      setSelectedChunks([]);
      setShowSelectedDrawer(false);
      const targetId = appendTargetTestSet.id;
      if (onClearAppendTarget) onClearAppendTarget();
      if (onTestSetCreated) {
        onTestSetCreated(targetId);
      }
    } catch (err) {
      addToast('error', '追加切片失败', formatErrorMessage(err));
    } finally {
      isSubmittingRef.current = false;
      setCreatingTestSet(false);
    }
  };

  const handleConfirmCreateTestSet = async (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedChunks.length === 0) return;
    if (isSubmittingRef.current || creatingTestSet) return;

    if (itemMode === 'multi' && selectedChunks.length > 5) {
      addToast('warning', '超出证据上限', '单道多证据题最多支持 5 块切片');
      return;
    }

    isSubmittingRef.current = true;
    setCreatingTestSet(true);

    try {
      let res: TestSet;
      if (testSetModalMode === 'create_new') {
        if (itemMode === 'multi') {
          const groupChunks = selectedChunks.map((c) => ({
            document_id: c.document_id,
            chunk_index: c.chunk_index,
          }));
          res = await api.createTestSetWithChunks(testSetName.trim() || undefined, {
            groups: [{ chunks: groupChunks }],
          });
          addToast(
            'success',
            '多证据评测集创建成功！',
            `评测集「${res.name}」已提交，后台 LLM Worker 将基于 ${groupChunks.length} 块证据切片生成综合多跳提问`
          );
        } else {
          const chunks = selectedChunks.map((c) => ({
            document_id: c.document_id,
            chunk_index: c.chunk_index,
          }));
          res = await api.createTestSetWithChunks(testSetName.trim() || undefined, { chunks });
          addToast(
            'success',
            '评测集创建成功！',
            `评测集「${res.name}」已提交，后台 LLM Worker 将异步为 ${chunks.length} 个切片分别出题`
          );
        }
      } else {
        if (!selectedExistingTestSetId) {
          addToast('warning', '请选择目标评测集');
          return;
        }

        if (itemMode === 'multi') {
          const groupChunks = selectedChunks.map((c) => ({
            document_id: c.document_id,
            chunk_index: c.chunk_index,
          }));
          res = await api.addItemsToTestSet(selectedExistingTestSetId, {
            groups: [{ chunks: groupChunks }],
          });
          addToast(
            'success',
            '多证据题已追加至评测集！',
            `已向评测集「${res.name}」追加 1 道多证据题目（含 ${groupChunks.length} 块证据）`
          );
        } else {
          const chunks = selectedChunks.map((c) => ({
            document_id: c.document_id,
            chunk_index: c.chunk_index,
          }));

          res = await api.addItemsToTestSet(selectedExistingTestSetId, { chunks });
          addToast(
            'success',
            '切片已追加至评测集！',
            `已向评测集「${res.name}」追加 ${chunks.length} 个切片出题任务`
          );
        }
      }

      setIsCreateTestSetModalOpen(false);
      setSelectedChunks([]);
      setShowSelectedDrawer(false);
      if (onTestSetCreated) {
        onTestSetCreated(res.id);
      }
    } catch (err) {
      addToast('error', '操作失败', formatErrorMessage(err));
    } finally {
      isSubmittingRef.current = false;
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
                    <div className="flex items-center gap-1 shrink-0">
                      {getStatusBadge(doc.status)}
                      {doc.status === 'failed' && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleReindexDoc(doc.id);
                          }}
                          disabled={reindexingDocId === doc.id}
                          className="p-1 rounded text-rose-600 hover:bg-rose-100 hover:text-rose-800 transition-colors cursor-pointer"
                          title="点击立即重试索引"
                        >
                          <RotateCw
                            className={`w-3 h-3 ${
                              reindexingDocId === doc.id ? 'animate-spin' : ''
                            }`}
                          />
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center justify-between gap-2 mt-2 text-[11px] font-mono text-slate-500">
                    <div className="flex items-center gap-2 truncate min-w-0">
                      <span className="flex items-center gap-1 shrink-0">
                        <Binary className="w-3 h-3 text-blue-600" />
                        <span>{doc.chunk_count || 0} 个切片</span>
                      </span>
                      {doc.graph && doc.graph.status !== 'none' && (
                        <span
                          title={`图谱状态: ${doc.graph.status}${doc.graph.error ? ' · ' + doc.graph.error : ''}`}
                          className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.2 rounded border font-mono shrink-0 ${
                            doc.graph.status === 'success'
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                              : doc.graph.status === 'failed'
                                ? 'bg-rose-50 text-rose-700 border-rose-200'
                                : 'bg-amber-50 text-amber-700 border-amber-200'
                          }`}
                        >
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${
                              doc.graph.status === 'success'
                                ? 'bg-emerald-500'
                                : doc.graph.status === 'failed'
                                  ? 'bg-rose-500'
                                : 'bg-amber-500'
                            }`}
                          />
                          {doc.graph.status === 'success'
                            ? '已入图'
                            : doc.graph.status === 'failed'
                              ? '图谱失败'
                              : '图谱抽取中'}
                        </span>
                      )}
                    </div>
                    <span className="shrink-0">
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

                  {selectedDoc.graph &&
                    (selectedDoc.graph.status === 'failed' ||
                      selectedDoc.graph.status === 'success') && (
                      <button
                        onClick={() => handleRerunGraph(selectedDoc.id)}
                        disabled={rerunningGraphDocId === selectedDoc.id}
                        className="flex items-center gap-1 px-2.5 py-1 text-xs font-mono font-semibold text-violet-800 hover:text-violet-900 bg-violet-50 hover:bg-violet-100 border border-violet-200 rounded-md transition-colors cursor-pointer disabled:opacity-50"
                        title={
                          selectedDoc.graph.status === 'failed'
                            ? '重跑图谱抽取（复位失败任务）'
                            : '重新抽取图谱（整篇幂等替换）'
                        }
                      >
                        <RotateCw
                          className={`w-3.5 h-3.5 text-violet-600 ${
                            rerunningGraphDocId === selectedDoc.id ? 'animate-spin' : ''
                          }`}
                        />
                        {selectedDoc.graph.status === 'failed' ? '重试抽取' : '重抽图谱'}
                      </button>
                    )}

                  {selectedDoc.graph &&
                    (selectedDoc.graph.status === 'pending' ||
                      selectedDoc.graph.status === 'queue') && (
                      <span
                        className="flex items-center gap-1 px-2.5 py-1 text-xs font-mono font-medium text-amber-800 bg-amber-50 border border-amber-200 rounded-md"
                        title="图谱抽取任务正在队列或执行中"
                      >
                        <RotateCw className="w-3.5 h-3.5 text-amber-600 animate-spin" />
                        <span>图谱抽取中…</span>
                      </span>
                    )}

                  {/* Reindex Button: FAILED 救回或 READY 重新切片 */}
                  {selectedDoc.status === 'failed' ? (
                    <button
                      onClick={() => handleReindexDoc(selectedDoc.id)}
                      disabled={reindexingDocId === selectedDoc.id}
                      className="flex items-center gap-1 px-2.5 py-1 text-xs font-mono font-semibold text-amber-800 hover:text-amber-900 bg-amber-50 hover:bg-amber-100 border border-amber-300 rounded-md transition-colors cursor-pointer disabled:opacity-50"
                      title="重新尝试解析与切片索引"
                    >
                      <RotateCw
                        className={`w-3.5 h-3.5 text-amber-600 ${
                          reindexingDocId === selectedDoc.id ? 'animate-spin' : ''
                        }`}
                      />
                      <span>{reindexingDocId === selectedDoc.id ? '提交中...' : '重试索引'}</span>
                    </button>
                  ) : selectedDoc.status === 'success' ? (
                    <button
                      onClick={() => handleReindexDoc(selectedDoc.id)}
                      disabled={reindexingDocId === selectedDoc.id}
                      className="flex items-center gap-1 px-2.5 py-1 text-xs font-mono text-slate-600 hover:text-slate-900 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-md transition-colors cursor-pointer disabled:opacity-50"
                      title="重新解析文档并重新生成切片、向量与图谱索引"
                    >
                      <RotateCw
                        className={`w-3.5 h-3.5 text-slate-500 ${
                          reindexingDocId === selectedDoc.id ? 'animate-spin' : ''
                        }`}
                      />
                      <span>{reindexingDocId === selectedDoc.id ? '重建中...' : '重新生成索引'}</span>
                    </button>
                  ) : null}

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
                    onClick={() => setConfirmDeleteDoc(selectedDoc)}
                    disabled={deleting}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs font-mono text-rose-600 hover:text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 rounded-md transition-colors cursor-pointer disabled:opacity-50"
                    title="删除该文档及其全部索引切片"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>删除文档</span>
                  </button>
                </div>
              </div>

              {/* Error Message banner if failed */}
              {selectedDoc.error_message && (
                <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-xs font-mono text-rose-700 flex items-center justify-between gap-3">
                  <div className="flex items-start gap-2 min-w-0">
                    <AlertCircle className="w-4 h-4 shrink-0 text-rose-600 mt-0.5" />
                    <div className="truncate">
                      <span className="font-bold">失败原因:</span> {selectedDoc.error_message}
                    </div>
                  </div>
                  <button
                    onClick={() => handleReindexDoc(selectedDoc.id)}
                    disabled={reindexingDocId === selectedDoc.id}
                    className="shrink-0 flex items-center gap-1 px-2.5 py-1 bg-rose-600 hover:bg-rose-700 active:bg-rose-800 text-white rounded text-xs font-semibold transition-colors cursor-pointer shadow-2xs disabled:opacity-50"
                  >
                    <RotateCw
                      className={`w-3 h-3 ${
                        reindexingDocId === selectedDoc.id ? 'animate-spin' : ''
                      }`}
                    />
                    <span>立即重试索引</span>
                  </button>
                </div>
              )}

              {/* Dedicated Knowledge Graph failure banner */}
              {selectedDoc.graph?.status === 'failed' && (
                <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-xs font-mono text-rose-700 flex items-center justify-between gap-3">
                  <div className="flex items-start gap-2 min-w-0">
                    <AlertCircle className="w-4 h-4 shrink-0 text-rose-600 mt-0.5" />
                    <div className="truncate">
                      <span className="font-bold">图谱抽取失败:</span>{' '}
                      {selectedDoc.graph.error || '图谱抽取遇到异常中断'}
                    </div>
                  </div>
                  <button
                    onClick={() => handleRerunGraph(selectedDoc.id)}
                    disabled={rerunningGraphDocId === selectedDoc.id}
                    className="shrink-0 flex items-center gap-1 px-2.5 py-1 bg-rose-600 hover:bg-rose-700 active:bg-rose-800 text-white rounded text-xs font-semibold transition-colors cursor-pointer shadow-2xs disabled:opacity-50"
                  >
                    <RotateCw
                      className={`w-3.5 h-3.5 ${
                        rerunningGraphDocId === selectedDoc.id ? 'animate-spin' : ''
                      }`}
                    />
                    <span>重试图谱抽取</span>
                  </button>
                </div>
              )}

              {/* Specs Grid */}
              <div
                className={`grid gap-3 pt-3 border-t border-slate-100 text-xs font-mono ${
                  selectedDoc.graph && selectedDoc.graph.status !== 'none'
                    ? 'grid-cols-2 sm:grid-cols-5'
                    : 'grid-cols-2 sm:grid-cols-4'
                }`}
              >
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

                {selectedDoc.graph && selectedDoc.graph.status !== 'none' && (
                  <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                    <span className="text-slate-500 text-[10px] block mb-0.5">知识图谱 (GRAPH)</span>
                    <span
                      className={`font-bold text-sm flex items-center gap-1.5 mt-0.5 ${
                        selectedDoc.graph.status === 'success'
                          ? 'text-emerald-700'
                          : selectedDoc.graph.status === 'failed'
                            ? 'text-rose-700'
                            : 'text-amber-700'
                      }`}
                    >
                      <span
                        className={`w-2 h-2 rounded-full shrink-0 ${
                          selectedDoc.graph.status === 'success'
                            ? 'bg-emerald-500'
                            : selectedDoc.graph.status === 'failed'
                              ? 'bg-rose-500'
                              : 'bg-amber-500'
                        }`}
                      />
                      {selectedDoc.graph.status === 'success'
                        ? '已入图'
                        : selectedDoc.graph.status === 'failed'
                          ? '抽取失败'
                          : '抽取中'}
                    </span>
                  </div>
                )}

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
                      {selectedChunks.length > 0 && (
                        <button
                          onClick={clearSelectedChunks}
                          className="px-2 py-1 text-[11px] rounded bg-slate-100 hover:bg-slate-200 border border-slate-200 text-slate-700 transition-colors cursor-pointer"
                        >
                          清空已选 ({selectedChunks.length})
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
                  正在从检索索引加载全部切片文本...
                </div>
              ) : filteredChunks.length > 0 ? (
                <div className="space-y-3">
                  {filteredChunks.map((chunk) => {
                    const isFocused = activeChunkTarget?.chunkIndex === chunk.chunk_index;
                    const isSelected = isChunkSelected(chunk.chunk_index);
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
                              onClick={() => toggleChunkSelection(chunk)}
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
      {selectedChunks.length > 0 && (
        <div className="absolute bottom-5 left-1/2 -translate-x-1/2 z-30 flex flex-col items-center gap-2 max-w-2xl w-[94%] sm:w-auto">
          {/* Drawer of selected chunks */}
          {showSelectedDrawer && (
            <div className="w-full bg-slate-900/95 text-white backdrop-blur-md px-4 py-3 rounded-2xl shadow-2xl border border-slate-700 space-y-2 animate-in fade-in slide-in-from-bottom-2 duration-150">
              <div className="flex items-center justify-between text-xs font-mono pb-1.5 border-b border-slate-800">
                <div className="flex items-center gap-1.5">
                  <Layers className="w-3.5 h-3.5 text-blue-400" />
                  <span className="font-bold">已选切片清单 ({selectedChunks.length})</span>
                  {itemMode === 'multi' && (
                    <span className="text-[10px] text-purple-300 bg-purple-900/60 px-1.5 py-0.2 rounded border border-purple-700">
                      按拼装顺序
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => setShowSelectedDrawer(false)}
                  className="text-slate-400 hover:text-white p-0.5 cursor-pointer"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>

              <div className="max-h-48 overflow-y-auto space-y-1.5 pr-1 text-xs font-mono">
                {selectedChunks.map((chunk, idx) => {
                  return (
                    <div
                      key={`${chunk.document_id}:${chunk.chunk_index}`}
                      className="flex items-center justify-between gap-2 p-2 rounded-lg border text-[11px] bg-slate-800/80 border-slate-700 text-slate-300"
                    >
                      <div className="flex items-center gap-1.5 truncate min-w-0">
                        {itemMode === 'multi' ? (
                          <span className="px-1.5 py-0.2 rounded text-[9px] font-bold bg-purple-600 text-white shrink-0">
                            切片 {idx + 1}
                          </span>
                        ) : (
                          <span className="px-1.5 py-0.2 rounded text-[9px] bg-slate-700 text-slate-400 shrink-0">
                            #{idx + 1}
                          </span>
                        )}
                        <span className="truncate max-w-[120px] font-medium" title={chunk.document_name}>
                          {chunk.document_name}
                        </span>
                        <span className="text-blue-400 font-bold shrink-0">
                          #chunk_{chunk.chunk_index + 1}
                        </span>
                        <span className="truncate text-slate-400 text-[10px] hidden sm:inline">
                          {chunk.text.replace(/\s+/g, ' ').substring(0, 30)}...
                        </span>
                      </div>

                      <button
                        type="button"
                        onClick={() => removeSelectedChunk(chunk.document_id, chunk.chunk_index)}
                        className="text-slate-400 hover:text-rose-400 p-0.5 cursor-pointer shrink-0"
                        title="移除此切片"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Main Floating Bar */}
          <div className="w-full bg-slate-900/95 text-white backdrop-blur-md px-4 py-2.5 rounded-2xl shadow-2xl border border-slate-700 flex flex-wrap items-center justify-between gap-3 animate-in fade-in slide-in-from-bottom-3 duration-200 font-mono text-xs">
            <div className="flex items-center gap-2.5">
              <CheckSquare className="w-4 h-4 text-blue-400 shrink-0" />
              <span>
                已选 <strong className="text-blue-300 text-sm">{selectedChunks.length}</strong> 块
              </span>

              {/* Cross-document indicator */}
              {(() => {
                const uniqueDocIds = new Set(selectedChunks.map((c) => c.document_id));
                if (uniqueDocIds.size > 1) {
                  return (
                    <span className="px-1.5 py-0.2 rounded text-[10px] bg-indigo-950 text-indigo-300 border border-indigo-700">
                      跨 {uniqueDocIds.size} 篇文档
                    </span>
                  );
                }
                return null;
              })()}

              <button
                type="button"
                onClick={() => setShowSelectedDrawer((prev) => !prev)}
                className="text-slate-400 hover:text-blue-300 text-[11px] underline underline-offset-2 cursor-pointer ml-1"
              >
                {showSelectedDrawer ? '收起清单' : '查看清单'}
              </button>
            </div>

            {/* Mode Switcher if >= 2 chunks */}
            {selectedChunks.length >= 2 && selectedChunks.length <= 5 && (
              <div className="flex items-center bg-slate-800 p-0.5 rounded-lg border border-slate-700 text-[11px]">
                <button
                  type="button"
                  onClick={() => setItemMode('single')}
                  className={`px-2 py-1 rounded-md transition-colors cursor-pointer ${
                    itemMode === 'single'
                      ? 'bg-blue-600 text-white font-bold shadow-xs'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  独立出题 ({selectedChunks.length}题)
                </button>
                <button
                  type="button"
                  onClick={() => setItemMode('multi')}
                  className={`px-2 py-1 rounded-md transition-colors cursor-pointer ${
                    itemMode === 'multi'
                      ? 'bg-purple-600 text-white font-bold shadow-xs'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  合成多证据 (1题)
                </button>
              </div>
            )}

            {selectedChunks.length > 5 && (
              <span className="text-[10px] text-slate-400 hidden sm:inline">
                (已选多于 5 块，按单题独立生成)
              </span>
            )}

            <div className="flex items-center gap-2">
              {appendTargetTestSet ? (
                <button
                  onClick={handleDirectAppend}
                  disabled={creatingTestSet}
                  className="flex items-center gap-1.5 px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white rounded-xl text-xs font-semibold shadow-md transition-all cursor-pointer"
                >
                  {creatingTestSet ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>正在提交 (POST /items)...</span>
                    </>
                  ) : itemMode === 'multi' ? (
                    <>
                      <Layers className="w-3.5 h-3.5" />
                      <span>合成 1 题追加至「{appendTargetTestSet.name}」➔</span>
                    </>
                  ) : (
                    <>
                      <Plus className="w-3.5 h-3.5" />
                      <span>追加 {selectedChunks.length} 题至「{appendTargetTestSet.name}」➔</span>
                    </>
                  )}
                </button>
              ) : (
                <button
                  onClick={handleOpenCreateTestSetModal}
                  className="flex items-center gap-1.5 px-3.5 py-1.5 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white rounded-xl text-xs font-semibold shadow-md transition-all cursor-pointer"
                >
                  {itemMode === 'multi' ? (
                    <Layers className="w-3.5 h-3.5 text-purple-200" />
                  ) : (
                    <Sparkles className="w-3.5 h-3.5 text-amber-300" />
                  )}
                  <span>
                    {itemMode === 'multi' ? '合成多证据评测 ➔' : '加入 / 创建评测集 ➔'}
                  </span>
                </button>
              )}

              <button
                onClick={clearSelectedChunks}
                className="text-slate-400 hover:text-slate-200 text-xs transition-colors cursor-pointer px-1"
              >
                清空
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create TestSet Modal */}
      {isCreateTestSetModalOpen && selectedChunks.length > 0 && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                {itemMode === 'multi' ? (
                  <Layers className="w-5 h-5 text-purple-600" />
                ) : (
                  <Sparkles className="w-5 h-5 text-blue-600" />
                )}
                <h3 className="text-sm font-bold text-slate-900 font-mono">
                  {testSetModalMode === 'create_new'
                    ? itemMode === 'multi'
                      ? '创建多证据评测集'
                      : '创建切片评测集'
                    : itemMode === 'multi'
                    ? '追加多证据题至评测集'
                    : '追加切片至评测集'}
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
              {/* Selected Chunks Overview */}
              <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl space-y-2 text-slate-700">
                <div className="flex items-center justify-between">
                  <span>勾选切片总数:</span>
                  <span className="font-bold text-blue-700">{selectedChunks.length} 块</span>
                </div>

                {/* Mode Selector within modal */}
                <div className="pt-2 border-t border-slate-200 space-y-1.5">
                  <span className="text-slate-600 font-medium block">出题模式选择:</span>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <label
                      className={`flex items-start gap-2 p-2.5 rounded-lg border cursor-pointer transition-colors ${
                        itemMode === 'single'
                          ? 'bg-blue-50/70 border-blue-500 text-blue-900'
                          : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50'
                      }`}
                    >
                      <input
                        type="radio"
                        name="modalItemMode"
                        checked={itemMode === 'single'}
                        onChange={() => setItemMode('single')}
                        className="mt-0.5 text-blue-600"
                      />
                      <div className="space-y-0.5">
                        <div className="font-bold">独立出题 (单证据)</div>
                        <div className="text-[10px] text-slate-500">
                          每块切片生成 1 道题，共 {selectedChunks.length} 题
                        </div>
                      </div>
                    </label>

                    <label
                      className={`flex items-start gap-2 p-2.5 rounded-lg border transition-colors ${
                        selectedChunks.length < 2 || selectedChunks.length > 5
                          ? 'opacity-50 cursor-not-allowed bg-slate-50 border-slate-200 text-slate-400'
                          : itemMode === 'multi'
                          ? 'bg-purple-50/70 border-purple-500 text-purple-900 cursor-pointer'
                          : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50 cursor-pointer'
                      }`}
                    >
                      <input
                        type="radio"
                        name="modalItemMode"
                        disabled={selectedChunks.length < 2 || selectedChunks.length > 5}
                        checked={itemMode === 'multi'}
                        onChange={() => setItemMode('multi')}
                        className="mt-0.5 text-purple-600"
                      />
                      <div className="space-y-0.5">
                        <div className="font-bold">合成多证据题 (多跳)</div>
                        <div className="text-[10px] text-slate-500">
                          {selectedChunks.length > 5
                            ? '单题最多 5 块切片（已超出）'
                            : selectedChunks.length < 2
                            ? '需选择至少 2 块切片'
                            : `合成 1 道综合多跳题目`}
                        </div>
                      </div>
                    </label>
                  </div>
                </div>

                {/* Evidence structure if multi */}
                {itemMode === 'multi' && (
                  <div className="pt-2 border-t border-slate-200 space-y-1.5">
                    <div className="flex items-center justify-between text-[11px] text-purple-900 font-bold">
                      <span>证据结构 (拼装顺序):</span>
                      <span className="text-[10px] text-purple-700">共 {selectedChunks.length} 块素材</span>
                    </div>
                    <div className="max-h-36 overflow-y-auto space-y-1 pr-1">
                      {selectedChunks.map((c, i) => (
                        <div
                          key={`${c.document_id}:${c.chunk_index}`}
                          className="flex items-center justify-between gap-1.5 p-1.5 bg-white rounded border border-purple-100 text-[11px]"
                        >
                          <div className="flex items-center gap-1.5 truncate">
                            <span className="px-1.5 py-0.2 rounded text-[9px] font-medium bg-purple-100 text-purple-800 shrink-0">
                              证据 {i + 1}
                            </span>
                            <span className="font-medium text-slate-800 truncate" title={c.document_name}>
                              {c.document_name}
                            </span>
                            <span className="text-purple-700 font-bold shrink-0">
                              #chunk_{c.chunk_index + 1}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
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

                  {selectedExistingTestSetId && (
                    <div className="p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-[11px] font-mono text-slate-600 space-y-1">
                      {itemMode === 'multi' ? (
                        <div className="flex items-center justify-between">
                          <span>预计新增出题:</span>
                          <strong className="text-purple-700">
                            1 道多证据题目（包含 {selectedChunks.length} 块切片）
                          </strong>
                        </div>
                      ) : (
                        <div className="flex items-center justify-between text-slate-700">
                          <span>预计新增出题:</span>
                          <strong className="text-emerald-700 font-semibold">{selectedChunks.length} 题</strong>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              <div className="p-3 bg-amber-50/70 border border-amber-200 rounded-lg text-[11px] text-amber-900 leading-relaxed">
                {itemMode === 'multi'
                  ? '💡 多证据模式下，LLM Worker 将综合全部片段素材反向出题，评测打分时需 Top-K 召回全部证据切片（块级全中）。'
                  : '💡 独立模式下，系统将为每块切片生成一条测试提问，评估检索定位各切片的准确率。'}
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
                  ) : itemMode === 'multi' ? (
                    <>
                      <Layers className="w-3.5 h-3.5" />
                      <span>
                        {testSetModalMode === 'create_new'
                          ? '确认创建多证据集'
                          : '确认追加多证据题'}
                      </span>
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

      {/* Delete Document Custom Confirmation Modal */}
      {confirmDeleteDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 max-w-md w-full p-6 space-y-4 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-xl bg-rose-100 flex items-center justify-center text-rose-600 shrink-0">
                <Trash2 className="w-5 h-5" />
              </div>
              <div className="space-y-1">
                <h3 className="font-bold text-slate-900 text-base">删除文档</h3>
                <p className="text-xs text-slate-500 leading-relaxed">
                  确定要彻底删除文档「<span className="font-semibold text-slate-800">{confirmDeleteDoc.name}</span>」吗？
                  此操作将永久清除该文档在文件存储及检索索引（Neo4j 向量与切片）中的全部数据，无法恢复。
                </p>
              </div>
            </div>
            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                type="button"
                onClick={() => setConfirmDeleteDoc(null)}
                disabled={deleting}
                className="px-4 py-2 rounded-xl border border-slate-200 text-slate-600 hover:bg-slate-100 text-xs font-semibold cursor-pointer disabled:opacity-50 transition-colors"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => executeDeleteDoc(confirmDeleteDoc)}
                disabled={deleting}
                className="px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold cursor-pointer disabled:opacity-50 transition-colors flex items-center gap-1.5 shadow-sm"
              >
                {deleting ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>删除中...</span>
                  </>
                ) : (
                  <>
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>确认删除</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
