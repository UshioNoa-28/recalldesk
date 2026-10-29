import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  TestSet,
  TargetChunkLink,
  EvalRun,
  EvalRunItem,
} from '../../types';
import { api, formatErrorMessage } from '../../api/client';
import { useToast } from '../../context/ToastContext';
import {
  BarChart2,
  Trash2,
  FileText,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Layers,
  Copy,
  Check,
  Search,
  Plus,
  X,
  Play,
  TrendingUp,
  Eye,
  RotateCw,
  UploadCloud,
} from 'lucide-react';

interface ItemAttribution {
  status: 'saved_by_rewrite' | 'rewrite_noise' | 'fusion_missed' | 'all_missed' | 'normal';
  label: string;
  badge: string;
  desc: string;
}

const getItemAttribution = (item: EvalRunItem): ItemAttribution => {
  if (!item.channels || item.channels.length === 0) {
    return { status: 'normal', label: '', badge: '', desc: '' };
  }
  const orig = item.channels.find((c) => c.kind === 'dense_original');
  const variants = item.channels.filter((c) => c.kind === 'dense_variant');
  const union = item.channels.find((c) => c.kind === 'union');

  if (orig && orig.recall === 0 && variants.some((v) => v.recall === 1)) {
    return {
      status: 'saved_by_rewrite',
      label: '✨ 改写净挽救',
      badge: 'bg-purple-100 text-purple-800 border-purple-200',
      desc: '原查询未全中，由 Query Rewrite 变体成功捞回全部证据',
    };
  }

  if (union && union.recall === 1 && item.recall === 0) {
    return {
      status: 'fusion_missed',
      label: '⚡ 融合截断',
      badge: 'bg-orange-100 text-orange-800 border-orange-200',
      desc: '单路已有通道成功全中，但多路融合或截断未保住',
    };
  }

  if (union && (!union.ranks || union.ranks.length === 0)) {
    return {
      status: 'all_missed',
      label: '❌ 索引缺失',
      badge: 'bg-slate-100 text-slate-600 border-slate-200',
      desc: '所有通道均未命中考查证据（数据未建索引或语义鸿沟）',
    };
  }

  if (orig && orig.recall === 1 && variants.length > 0 && variants.every((v) => v.recall === 0)) {
    return {
      status: 'rewrite_noise',
      label: '⚠️ 改写弱化',
      badge: 'bg-amber-100 text-amber-800 border-amber-200',
      desc: '原查询全中，但改写变体未命中考查证据',
    };
  }

  return { status: 'normal', label: '', badge: '', desc: '' };
};

interface EvaluationStudioProps {
  selectedTestSetId?: string | null;
  onNavigateToChunk?: (target: TargetChunkLink) => void;
  onUpdateTestSetCount?: (count: number) => void;
}

export const EvaluationStudio: React.FC<EvaluationStudioProps> = ({
  selectedTestSetId,
  onNavigateToChunk,
  onUpdateTestSetCount,
}) => {
  const [testSets, setTestSets] = useState<TestSet[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedTestSet, setSelectedTestSet] = useState<TestSet | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [autoPolling, setAutoPolling] = useState(true);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteSet, setConfirmDeleteSet] = useState<TestSet | null>(null);
  const [docMap, setDocMap] = useState<Record<string, string>>({});

  // Direct Create Modal
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [newSetName, setNewSetName] = useState('');
  const [creatingSet, setCreatingSet] = useState(false);

  // Import JSONL Questions Modal
  const [isImportModalOpen, setIsImportModalOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Eval Runs State
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [activeTab, setActiveTab] = useState<'items' | 'runs'>('items');
  const [isLaunchRunModalOpen, setIsLaunchRunModalOpen] = useState(false);
  const [runTopK, setRunTopK] = useState(5);
  const [runQueryRewrite, setRunQueryRewrite] = useState(true);
  const [runRerank, setRunRerank] = useState(true);
  const [launchingRun, setLaunchingRun] = useState(false);
  const [selectedRunDetail, setSelectedRunDetail] = useState<EvalRun | null>(null);
  const [rerunningRunId, setRerunningRunId] = useState<string | null>(null);
  const [loadingRunDetail, setLoadingRunDetail] = useState(false);
  const [isRunDetailModalOpen, setIsRunDetailModalOpen] = useState(false);

  const { addToast } = useToast();
  const pollingTimerRef = useRef<number | null>(null);
  const selectedTestSetRef = useRef<TestSet | null>(selectedTestSet);
  const runsRef = useRef<EvalRun[]>([]);

  useEffect(() => {
    selectedTestSetRef.current = selectedTestSet;
  }, [selectedTestSet]);

  useEffect(() => {
    runsRef.current = runs;
  }, [runs]);

  useEffect(() => {
    const loadDocMap = async () => {
      try {
        const res = await api.listDocuments(1, 100);
        const map: Record<string, string> = {};
        for (const doc of res.items || []) {
          map[doc.id] = doc.name;
        }
        setDocMap(map);
      } catch {
        // Ignore
      }
    };
    loadDocMap();
  }, []);

  const fetchTestSetDetail = useCallback(
    async (testsetId: string, silent = false) => {
      if (!silent) setLoadingDetail(true);
      try {
        const detail = await api.getTestSet(testsetId);
        setSelectedTestSet(detail);
      } catch (err) {
        setSelectedTestSet(null);
        if (window.location.hash.startsWith('#/evaluation/')) {
          window.location.hash = '#/evaluation';
        }
        if (!silent) {
          addToast('error', '获取评测集详情失败', formatErrorMessage(err));
        }
      } finally {
        if (!silent) setLoadingDetail(false);
      }
    },
    [addToast]
  );

  const fetchRuns = useCallback(async (testsetId: string, silent = false) => {
    if (!silent) setLoadingRuns(true);
    try {
      const list = await api.listRuns(testsetId);
      setRuns(list);
    } catch {
      // Ignore
    } finally {
      if (!silent) setLoadingRuns(false);
    }
  }, []);

  const handleRerunFailedRun = async (runId: string) => {
    setRerunningRunId(runId);
    try {
      const updated = await api.rerunEvalRun(runId);
      setSelectedRunDetail(updated);
      addToast('success', '已提交重跑', '失败题已复位，评测在后台继续跑');
      if (selectedTestSet) fetchRuns(selectedTestSet.id, true);
    } catch (err) {
      addToast('error', '重跑失败', formatErrorMessage(err));
    } finally {
      setRerunningRunId(null);
    }
  };

  const fetchRunDetail = useCallback(async (runId: string, silent = false) => {
    if (!silent) setLoadingRunDetail(true);
    try {
      const detail = await api.getRun(runId);
      setSelectedRunDetail(detail);
    } catch (err) {
      if (!silent) {
        addToast('error', '获取评测运行详情失败', formatErrorMessage(err));
      }
    } finally {
      if (!silent) setLoadingRunDetail(false);
    }
  }, [addToast]);

  const handleOpenRunDetail = async (run: EvalRun) => {
    setSelectedRunDetail(run);
    setIsRunDetailModalOpen(true);
    await fetchRunDetail(run.id, false);
  };

  const handleStartRun = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedTestSet) return;
    setLaunchingRun(true);

    try {
      await api.createRun(
        selectedTestSet.id,
        {
          top_k: runTopK,
          query_rewrite: runQueryRewrite,
          rerank: runRerank,
        }
      );

      addToast('success', '检索评测已启动', `评测运行已受理（状态码 202）`);
      setIsLaunchRunModalOpen(false);
      setActiveTab('runs');
      await fetchRuns(selectedTestSet.id);
    } catch (err) {
      addToast('error', '发起评测失败', formatErrorMessage(err));
    } finally {
      setLaunchingRun(false);
    }
  };

  useEffect(() => {
    if (isRunDetailModalOpen && selectedRunDetail && selectedRunDetail.status === 'running') {
      const timer = window.setInterval(() => {
        fetchRunDetail(selectedRunDetail.id, true);
      }, 2000);
      return () => clearInterval(timer);
    }
  }, [isRunDetailModalOpen, selectedRunDetail, fetchRunDetail]);

  const fetchTestSets = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        const list = await api.listTestSets();
        setTestSets(list);
        if (onUpdateTestSetCount) {
          onUpdateTestSetCount(list.length);
        }

        const current = selectedTestSetRef.current;
        let targetToLoad: string | null = null;

        if (selectedTestSetId && list.some((t) => t.id === selectedTestSetId)) {
          targetToLoad = selectedTestSetId;
        } else if (current && list.some((t) => t.id === current.id)) {
          targetToLoad = current.id;
        } else if (list.length > 0) {
          targetToLoad = list[0].id;
          if (selectedTestSetId && !list.some((t) => t.id === selectedTestSetId)) {
            window.location.hash = `#/evaluation/${list[0].id}`;
          }
        } else {
          setSelectedTestSet(null);
          if (window.location.hash.startsWith('#/evaluation/')) {
            window.location.hash = '#/evaluation';
          }
        }

        if (targetToLoad) {
          const match = list.find((t) => t.id === targetToLoad);
          if (match) {
            setSelectedTestSet((prev) => (prev && prev.id === match.id ? { ...prev, ...match } : match));
          }
          fetchTestSetDetail(targetToLoad, true);
          fetchRuns(targetToLoad, true);
        }
      } catch (err) {
        if (!silent) {
          addToast('error', '获取评测集列表失败', formatErrorMessage(err));
        }
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [selectedTestSetId, onUpdateTestSetCount, addToast, fetchTestSetDetail, fetchRuns]
  );

  useEffect(() => {
    fetchTestSets();
  }, [fetchTestSets]);

  // Polling runs that are in 'running' status
  useEffect(() => {
    if (autoPolling) {
      pollingTimerRef.current = window.setInterval(() => {
        const current = selectedTestSetRef.current;
        const currentRuns = runsRef.current;
        const hasRunningRun = currentRuns.some((r) => r.status === 'running');
        if (current && hasRunningRun) {
          fetchRuns(current.id, true);
        }
      }, 3000);
    }
    return () => {
      if (pollingTimerRef.current) clearInterval(pollingTimerRef.current);
    };
  }, [autoPolling, fetchRuns]);

  const handleSelectTestSet = (ts: TestSet) => {
    setSelectedTestSet(ts);
    window.location.hash = `#/evaluation/${ts.id}`;
    fetchTestSetDetail(ts.id);
    fetchRuns(ts.id);
  };

  const executeDeleteTestSet = async (ts: TestSet) => {
    setDeletingId(ts.id);
    try {
      await api.deleteTestSet(ts.id);
      addToast('success', '评测集已删除', `「${ts.name}」已清除`);
      if (selectedTestSet?.id === ts.id) {
        setSelectedTestSet(null);
      }
      setConfirmDeleteSet(null);
      window.location.hash = '#/evaluation';
      await fetchTestSets();
    } catch (err) {
      addToast('error', '删除评测集失败', formatErrorMessage(err));
    } finally {
      setDeletingId(null);
    }
  };

  const handleCreateEmptyTestSet = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreatingSet(true);
    try {
      const res = await api.createTestSet(newSetName.trim() || undefined);
      addToast('success', '评测集创建成功', `评测集「${res.name}」已创建`);
      setIsCreateModalOpen(false);
      setNewSetName('');
      await fetchTestSets();
      setSelectedTestSet(res);
      window.location.hash = `#/evaluation/${res.id}`;
    } catch (err) {
      addToast('error', '创建评测集失败', formatErrorMessage(err));
    } finally {
      setCreatingSet(false);
    }
  };

  const handleImportJsonl = async () => {
    if (!selectedTestSet || !selectedFile) {
      setImportError('请选择要导入的 .jsonl 题目文件');
      return;
    }

    if (!selectedFile.name.toLowerCase().endsWith('.jsonl')) {
      setImportError('题目文件只认 .jsonl 后缀');
      return;
    }

    if (selectedFile.size === 0) {
      setImportError('文件内容为空');
      return;
    }

    if (selectedFile.size > 2 * 1024 * 1024) {
      setImportError('文件大小超出 2 MiB 限制');
      return;
    }

    setImporting(true);
    setImportError(null);
    try {
      const updated = await api.uploadTestSetItems(selectedTestSet.id, selectedFile);
      addToast('success', '题目导入成功', `已同步解析引文，当前题目总数: ${updated.item_count} 题`);
      setSelectedTestSet(updated);
      setIsImportModalOpen(false);
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      await fetchTestSets(true);
    } catch (err) {
      const msg = formatErrorMessage(err);
      setImportError(msg);
      addToast('error', '导入题目失败', msg);
    } finally {
      setImporting(false);
    }
  };

  const handleCopy = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(key);
    setTimeout(() => setCopiedId(null), 2000);
    addToast('info', '已复制到剪贴板');
  };

  const filteredTestSets = testSets.filter((t) => {
    return t.name.toLowerCase().includes(searchTerm.toLowerCase());
  });

  return (
    <div className="flex-1 flex flex-col md:flex-row min-h-0 bg-slate-50 overflow-hidden">
      {/* Left Master Pane: TestSets List */}
      <div className="w-full md:w-5/12 lg:w-4/12 border-r border-slate-200 flex flex-col bg-white min-h-0">
        <div className="p-3.5 border-b border-slate-200 space-y-2.5 bg-slate-50/70">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5 font-mono font-bold text-slate-800">
              <BarChart2 className="w-3.5 h-3.5 text-blue-600" />
              <span>评测集管理 ({testSets.length})</span>
            </div>

            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setIsCreateModalOpen(true)}
                className="flex items-center gap-1 px-2 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded text-[11px] font-mono font-semibold transition-colors cursor-pointer shadow-2xs"
                title="创建空评测集"
              >
                <Plus className="w-3 h-3" />
                <span>新建</span>
              </button>

              <label className="flex items-center gap-1 text-[11px] font-mono text-slate-500 cursor-pointer ml-1">
                <input
                  type="checkbox"
                  checked={autoPolling}
                  onChange={(e) => setAutoPolling(e.target.checked)}
                  className="rounded bg-white border-slate-300 text-blue-600 w-3 h-3"
                />
                <span>轮询</span>
              </label>

              <button
                onClick={() => fetchTestSets(false)}
                disabled={loading}
                className="p-1 rounded bg-white hover:bg-slate-100 border border-slate-200 text-slate-500 hover:text-slate-800 transition-colors cursor-pointer"
                title="刷新评测集列表"
              >
                <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>

          <div className="relative">
            <Search className="w-3 h-3 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="搜索评测集名称..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-7 pr-2.5 py-1.5 bg-white border border-slate-300 rounded text-xs font-mono text-slate-900 placeholder-slate-400 focus:outline-none focus:border-blue-600 focus:ring-1 focus:ring-blue-100"
            />
          </div>
        </div>

        {/* TestSets List */}
        <div className="flex-1 overflow-y-auto divide-y divide-slate-100">
          {loading && testSets.length === 0 ? (
            <div className="p-8 text-center text-slate-400 font-mono text-xs">
              <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-blue-600" />
              正在加载评测集列表...
            </div>
          ) : filteredTestSets.length === 0 ? (
            <div className="p-8 text-center text-slate-400 font-mono text-xs space-y-2">
              <p>暂无评测集</p>
              <button
                onClick={() => setIsCreateModalOpen(true)}
                className="text-blue-600 hover:underline inline-flex items-center gap-1 font-semibold"
              >
                <Plus className="w-3 h-3" />
                <span>立即新建评测集</span>
              </button>
            </div>
          ) : (
            filteredTestSets.map((ts) => {
              const isSelected = selectedTestSet?.id === ts.id;

              return (
                <div
                  key={ts.id}
                  onClick={() => handleSelectTestSet(ts)}
                  className={`p-3.5 cursor-pointer transition-colors ${
                    isSelected
                      ? 'bg-blue-50/70 border-l-3 border-l-blue-600'
                      : 'hover:bg-slate-50'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 truncate min-w-0">
                      <Layers
                        className={`w-4 h-4 shrink-0 ${
                          isSelected ? 'text-blue-600' : 'text-slate-400'
                        }`}
                      />
                      <span className="text-sm font-mono text-slate-900 font-semibold truncate">
                        {ts.name}
                      </span>
                    </div>

                    <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-blue-100 text-blue-800 border border-blue-200">
                      {ts.item_count} 题
                    </span>
                  </div>

                  <div className="flex items-center justify-between mt-2 text-[11px] font-mono text-slate-500">
                    <span>同步解析入库</span>
                    <span>
                      {ts.created_at
                        ? new Date(ts.created_at).toLocaleTimeString('zh-CN', {
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
      </div>

      {/* Right Detail Pane */}
      <div className="flex-1 flex flex-col bg-slate-50 overflow-y-auto p-6 space-y-4">
        {selectedTestSet ? (
          <div className="max-w-5xl space-y-4">
            {/* Header Card */}
            <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-4 shadow-xs">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2.5">
                    <BarChart2 className="w-5 h-5 text-blue-600" />
                    <h2 className="text-base font-bold font-mono text-slate-900 break-all">
                      {selectedTestSet.name}
                    </h2>
                  </div>
                  <div className="flex items-center gap-2 text-xs font-mono text-slate-500">
                    <span>UUID: {selectedTestSet.id}</span>
                    <button
                      onClick={() => handleCopy(selectedTestSet.id, 'tsId')}
                      className="hover:text-slate-800 transition-colors cursor-pointer"
                      title="复制评测集 ID"
                    >
                      {copiedId === 'tsId' ? (
                        <Check className="w-3.5 h-3.5 text-emerald-600" />
                      ) : (
                        <Copy className="w-3.5 h-3.5 text-slate-400" />
                      )}
                    </button>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {/* Upload JSONL button */}
                  <button
                    onClick={() => {
                      setImportError(null);
                      setSelectedFile(null);
                      setIsImportModalOpen(true);
                    }}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-mono font-semibold text-purple-700 bg-purple-50 hover:bg-purple-100 border border-purple-200 rounded-lg transition-colors cursor-pointer"
                  >
                    <UploadCloud className="w-3.5 h-3.5" />
                    <span>导入题目 (.jsonl)</span>
                  </button>

                  {/* Launch Run Button */}
                  <button
                    onClick={() => setIsLaunchRunModalOpen(true)}
                    disabled={selectedTestSet.item_count === 0 || runs.some((r) => r.status === 'running')}
                    className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-mono font-bold text-white bg-blue-600 hover:bg-blue-700 active:bg-blue-800 disabled:bg-slate-300 disabled:cursor-not-allowed rounded-lg transition-colors cursor-pointer shadow-xs"
                    title={
                      selectedTestSet.item_count === 0
                        ? '请先导入至少 1 道题目方可发起评测'
                        : runs.some((r) => r.status === 'running')
                        ? '当前已有评测运行正在执行中'
                        : '对该评测集发起检索召回与排序评测'
                    }
                  >
                    <Play className="w-3.5 h-3.5 fill-current" />
                    <span>发起评测</span>
                  </button>

                  {/* Delete TestSet Button */}
                  <button
                    onClick={() => setConfirmDeleteSet(selectedTestSet)}
                    disabled={deletingId === selectedTestSet.id}
                    className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-mono text-rose-600 hover:text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 rounded-lg transition-colors cursor-pointer disabled:opacity-50"
                    title="删除评测集及其所有题目"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>{deletingId === selectedTestSet.id ? '删除中...' : '删除'}</span>
                  </button>
                </div>
              </div>

              {/* Progress Overview Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-3 border-t border-slate-100 text-xs font-mono">
                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <span className="text-slate-500 text-[10px] block mb-0.5">题目总数</span>
                  <span className="text-blue-700 font-bold text-base">
                    {selectedTestSet.item_count} 题
                  </span>
                </div>

                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <span className="text-slate-500 text-[10px] block mb-0.5">创建时间</span>
                  <span className="text-slate-800 text-[11px] truncate block font-medium">
                    {selectedTestSet.created_at ? new Date(selectedTestSet.created_at).toLocaleString() : '—'}
                  </span>
                </div>

                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <span className="text-slate-500 text-[10px] block mb-0.5">历史评测运行</span>
                  <span className="text-purple-700 font-bold text-base">
                    {runs.length} 次
                  </span>
                </div>

                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <span className="text-slate-500 text-[10px] block mb-0.5">题目导入方式</span>
                  <span className="text-emerald-700 text-[11px] truncate block font-semibold">
                    JSONL 同步解析引文
                  </span>
                </div>
              </div>
            </div>

            {/* Tab Navigation: Questions vs Runs */}
            <div className="flex border-b border-slate-200 text-xs font-mono">
              <button
                type="button"
                onClick={() => setActiveTab('items')}
                className={`flex items-center gap-2 py-2.5 px-4 font-bold border-b-2 transition-colors cursor-pointer ${
                  activeTab === 'items'
                    ? 'border-blue-600 text-blue-600 bg-white rounded-t-lg'
                    : 'border-transparent text-slate-500 hover:text-slate-800'
                }`}
              >
                <FileText className="w-3.5 h-3.5" />
                <span>题目明细 ({selectedTestSet.item_count} 题)</span>
              </button>

              <button
                type="button"
                onClick={() => setActiveTab('runs')}
                className={`flex items-center gap-2 py-2.5 px-4 font-bold border-b-2 transition-colors cursor-pointer ${
                  activeTab === 'runs'
                    ? 'border-blue-600 text-blue-600 bg-white rounded-t-lg'
                    : 'border-transparent text-slate-500 hover:text-slate-800'
                }`}
              >
                <TrendingUp className="w-3.5 h-3.5" />
                <span>评测运行与指标 ({runs.length})</span>
                {runs.some((r) => r.status === 'running') && (
                  <span className="w-2 h-2 rounded-full bg-amber-500 animate-ping" />
                )}
              </button>
            </div>

            {/* Tab 1: Questions */}
            {activeTab === 'items' ? (
              <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-4 shadow-xs">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-mono">
                  <div className="flex items-center gap-1.5 text-slate-900 font-bold">
                    <FileText className="w-4 h-4 text-blue-600" />
                    <span>题目清单 ({selectedTestSet.item_count} 题)</span>
                  </div>

                  <span className="text-[11px] text-slate-400">
                    导入即终态，系统已精准/近似解析每段考查引文所在切片
                  </span>
                </div>

                {loadingDetail ? (
                  <div className="p-8 text-center text-slate-400 font-mono text-xs">
                    <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-blue-600" />
                    正在加载题目详情...
                  </div>
                ) : selectedTestSet.items && selectedTestSet.items.length > 0 ? (
                  <div className="space-y-3">
                    {selectedTestSet.items.map((item, idx) => {
                      const evidenceList = item.evidence || [];

                      return (
                        <div
                          key={item.id || idx}
                          className="p-4 bg-slate-50/70 border border-slate-200 rounded-xl space-y-3 hover:border-slate-300 transition-colors"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-200/80 text-xs font-mono">
                            <div className="flex items-center gap-2 min-w-0">
                              <span className="w-5 h-5 rounded bg-white border border-slate-200 flex items-center justify-center text-[10px] font-bold text-slate-700">
                                #{idx + 1}
                              </span>
                              <span className="text-slate-500 font-medium">
                                题目 ID: {item.id}
                              </span>
                            </div>
                            <span className="text-[11px] text-purple-700 bg-purple-50 px-2 py-0.5 rounded border border-purple-200 font-semibold">
                              {evidenceList.length} 段考查引文
                            </span>
                          </div>

                          {/* Query Content */}
                          <div className="p-3 bg-white border border-slate-200 rounded-lg text-sm font-mono text-slate-900 leading-relaxed font-semibold">
                            {item.query}
                          </div>

                          {/* Evidence list */}
                          {evidenceList.length > 0 && (
                            <div className="space-y-2 pt-1 font-mono text-xs">
                              <div className="text-xs text-slate-500 font-semibold">考查证据（文档切片）：</div>
                              <div className="space-y-1.5">
                                {evidenceList.map((ev, eIdx) => {
                                  const docName = docMap[ev.document_id] || `文档 ${ev.document_id.substring(0, 8)}...`;

                                  return (
                                    <div
                                      key={eIdx}
                                      className="flex flex-wrap items-center justify-between gap-2 p-2.5 rounded-lg border border-slate-200 bg-white"
                                    >
                                      <div className="flex items-center gap-2 min-w-0">
                                        <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-slate-100 text-slate-700">
                                          证据 #{eIdx + 1}
                                        </span>
                                        <span className="text-slate-800 font-medium truncate max-w-xs sm:max-w-md text-xs" title={docName}>
                                          {docName}
                                        </span>
                                      </div>

                                      <div className="flex items-center gap-1.5">
                                        <button
                                          type="button"
                                          onClick={() => {
                                            if (onNavigateToChunk) {
                                              onNavigateToChunk({
                                                documentId: ev.document_id,
                                                chunkIndex: ev.chunk_index,
                                                documentName: docName,
                                              });
                                            }
                                          }}
                                          className="px-2 py-0.5 rounded text-xs bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200 font-bold cursor-pointer transition-colors"
                                          title="点击在文档浏览器中查看此切片"
                                        >
                                          #chunk_{ev.chunk_index + 1}
                                        </button>
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="p-12 text-center text-slate-400 font-mono text-xs space-y-3">
                    <Layers className="w-8 h-8 mx-auto text-slate-300" />
                    <p>当前评测集暂无题目</p>
                    <button
                      onClick={() => {
                        setImportError(null);
                        setSelectedFile(null);
                        setIsImportModalOpen(true);
                      }}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-semibold font-mono transition-colors cursor-pointer"
                    >
                      <UploadCloud className="w-3.5 h-3.5" />
                      <span>上传 .jsonl 题目文件导入 ➔</span>
                    </button>
                  </div>
                )}
              </div>
            ) : (
              /* Tab 2: Runs */
              <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-4 shadow-xs">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-mono">
                  <div className="flex items-center gap-1.5 text-slate-900 font-bold">
                    <TrendingUp className="w-4 h-4 text-blue-600" />
                    <span>检索召回与排序评测记录 ({runs.length} 次运行)</span>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => fetchRuns(selectedTestSet.id)}
                      disabled={loadingRuns}
                      className="p-1 rounded bg-white hover:bg-slate-100 border border-slate-200 text-slate-500 hover:text-slate-800 transition-colors cursor-pointer"
                      title="刷新评测运行记录"
                    >
                      <RefreshCw className={`w-3 h-3 ${loadingRuns ? 'animate-spin' : ''}`} />
                    </button>

                    <button
                      onClick={() => setIsLaunchRunModalOpen(true)}
                      disabled={selectedTestSet.item_count === 0 || runs.some((r) => r.status === 'running')}
                      className="flex items-center gap-1 px-3 py-1 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-300 disabled:cursor-not-allowed text-white rounded text-xs font-mono font-semibold transition-colors cursor-pointer shadow-2xs"
                    >
                      <Play className="w-3 h-3 fill-current" />
                      <span>发起评测</span>
                    </button>
                  </div>
                </div>

                {loadingRuns && runs.length === 0 ? (
                  <div className="p-8 text-center text-slate-400 font-mono text-xs">
                    <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-blue-600" />
                    正在加载评测记录...
                  </div>
                ) : runs.length === 0 ? (
                  <div className="p-12 text-center text-slate-400 font-mono text-xs space-y-3 bg-slate-50 rounded-xl border border-dashed border-slate-200">
                    <BarChart2 className="w-8 h-8 text-slate-400 mx-auto" />
                    <div className="space-y-1">
                      <p className="font-bold text-slate-600">暂无评测运行记录</p>
                      <p className="text-[11px] text-slate-400">
                        点击「发起评测」按钮，系统将自动使用已导入的题目测试证据全中率 (Recall@K) 与平均精度 (MAP@K)。
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {runs.map((run, idx) => {
                      const k = run.config.top_k || 5;
                      const recallKey = `recall@${k}`;
                      const mapKey = `map@${k}`;
                      const recallVal = run.metrics && recallKey in run.metrics ? run.metrics[recallKey] : null;
                      const mapVal = run.metrics && mapKey in run.metrics ? run.metrics[mapKey] : null;

                      return (
                        <div
                          key={run.id}
                          className={`p-4 rounded-xl border transition-all ${
                            run.status === 'running'
                              ? 'bg-amber-50/40 border-amber-300 shadow-sm'
                              : 'bg-slate-50/70 border-slate-200 hover:border-slate-300'
                          }`}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-200/80 text-xs font-mono">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="w-5 h-5 rounded bg-white border border-slate-200 flex items-center justify-center text-[10px] font-bold text-slate-700">
                                #{runs.length - idx}
                              </span>

                              {run.status === 'running' ? (
                                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-100 text-amber-800 border border-amber-200">
                                  <RefreshCw className="w-3 h-3 animate-spin text-amber-600" />
                                  检索评测中 ({run.progress_done} / {run.progress_total})
                                </span>
                              ) : run.status === 'done' ? (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-100 text-emerald-800 border border-emerald-200">
                                  <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                                  评测完成
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-100 text-rose-800 border border-rose-200">
                                  <AlertCircle className="w-3 h-3 text-rose-600" />
                                  失败
                                </span>
                              )}

                              <span className="text-[11px] text-slate-400">
                                UUID: {run.id.substring(0, 8)}...
                              </span>

                              <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-200/70 text-slate-700 font-mono">
                                Top-K: {k}
                              </span>
                            </div>

                            <div className="flex items-center gap-2 sm:gap-3">
                              <span className="text-[11px] text-slate-400">
                                {run.created_at ? new Date(run.created_at).toLocaleString('zh-CN') : '—'}
                              </span>

                              {run.status === 'failed' && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleRerunFailedRun(run.id);
                                  }}
                                  disabled={rerunningRunId === run.id}
                                  className="flex items-center gap-1 px-2.5 py-1 rounded bg-rose-50 hover:bg-rose-100 border border-rose-200 text-rose-700 text-xs font-semibold font-mono transition-colors cursor-pointer disabled:opacity-50"
                                >
                                  <RotateCw className={`w-3.5 h-3.5 ${rerunningRunId === run.id ? 'animate-spin' : ''}`} />
                                  <span>重跑失败题</span>
                                </button>
                              )}

                              <button
                                onClick={() => handleOpenRunDetail(run)}
                                className="flex items-center gap-1 px-2.5 py-1 rounded bg-white hover:bg-slate-100 border border-slate-200 text-blue-700 text-xs font-semibold transition-colors cursor-pointer shadow-2xs"
                              >
                                <Eye className="w-3.5 h-3.5 text-blue-600" />
                                <span>打分明细 ➔</span>
                              </button>
                            </div>
                          </div>

                          {/* Progress bar if running */}
                          {run.status === 'running' && (
                            <div className="mt-3 space-y-1">
                              <div className="flex items-center justify-between text-[11px] font-mono text-amber-800">
                                <span>评测进度</span>
                                <span>{run.progress_done} / {run.progress_total} 题</span>
                              </div>
                              <div className="w-full h-1.5 bg-amber-100 rounded-full overflow-hidden">
                                <div
                                  className="h-full bg-amber-500 rounded-full transition-all duration-300"
                                  style={{
                                    width: `${run.progress_total > 0 ? (run.progress_done / run.progress_total) * 100 : 0}%`,
                                  }}
                                />
                              </div>
                            </div>
                          )}

                          {/* Metrics summary */}
                          {run.metrics && (
                            <div className="mt-3 grid gap-2 text-xs font-mono grid-cols-2 sm:grid-cols-4">
                              <div className="p-2.5 bg-white rounded-lg border border-slate-200/90 shadow-2xs">
                                <span className="text-slate-400 text-[10px] block mb-0.5">
                                  证据全中 ({recallKey})
                                </span>
                                <span className="text-emerald-700 font-bold text-sm">
                                  {recallVal !== null && recallVal !== undefined ? `${(Number(recallVal) * 100).toFixed(1)}%` : '—'}
                                </span>
                              </div>

                              <div className="p-2.5 bg-white rounded-lg border border-slate-200/90 shadow-2xs">
                                <span className="text-slate-400 text-[10px] block mb-0.5">
                                  平均精度 ({mapKey})
                                </span>
                                <span className="text-blue-700 font-bold text-sm">
                                  {mapVal !== null && mapVal !== undefined ? Number(mapVal).toFixed(4) : '—'}
                                </span>
                              </div>

                              <div className="p-2.5 bg-white rounded-lg border border-slate-200/90 shadow-2xs">
                                <span className="text-slate-400 text-[10px] block mb-0.5">
                                  平均延迟
                                </span>
                                <span className="text-slate-800 font-bold text-sm">
                                  {run.metrics?.avg_latency_ms ? `${Number(run.metrics.avg_latency_ms).toFixed(1)} ms` : '—'}
                                </span>
                              </div>

                              <div className="p-2.5 bg-white rounded-lg border border-slate-200/90 shadow-2xs">
                                <span className="text-slate-400 text-[10px] block mb-0.5">
                                  考查题目数
                                </span>
                                <span className="text-purple-700 font-bold text-sm">
                                  {run.progress_total} 题
                                </span>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center p-16 text-slate-400 font-mono text-xs space-y-2">
            <BarChart2 className="w-8 h-8 text-slate-400" />
            <p>请在左侧列表中选择一个评测集查看其题目与评测运行</p>
          </div>
        )}
      </div>

      {/* Import JSONL Questions Modal */}
      {isImportModalOpen && selectedTestSet && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <UploadCloud className="w-5 h-5 text-purple-600" />
                <h3 className="text-sm font-bold text-slate-900 font-mono">
                  导入题目文件 (.jsonl)
                </h3>
              </div>
              <button
                onClick={() => setIsImportModalOpen(false)}
                className="text-slate-400 hover:text-slate-700 p-1 rounded-lg cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs font-mono">
              <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl space-y-1">
                <span className="text-slate-500 text-[11px] block">目标评测集:</span>
                <strong className="text-slate-900 font-bold block">{selectedTestSet.name}</strong>
              </div>

              {importError && (
                <div className="p-3 bg-rose-50 border border-rose-200 rounded-xl space-y-1 text-xs text-rose-700">
                  <div className="flex items-center gap-1.5 font-bold">
                    <AlertCircle className="w-4 h-4 text-rose-500" />
                    <span>导入被整份拒绝：</span>
                  </div>
                  <pre className="whitespace-pre-wrap break-all text-[11px] font-mono leading-relaxed bg-white/70 p-2 rounded border border-rose-200">
                    {importError}
                  </pre>
                </div>
              )}

              {/* Specification explanation */}
              <div className="space-y-1.5 text-slate-600 text-xs leading-relaxed">
                <p className="font-semibold text-slate-800">• 契约格式要求：</p>
                <p>文件仅接受 <code className="bg-purple-50 text-purple-700 px-1 py-0.5 rounded border border-purple-200 font-bold">.jsonl</code>（上限 2 MiB），一行一题：</p>
                <pre className="bg-slate-900 text-slate-200 p-2.5 rounded-lg text-xs font-mono overflow-x-auto whitespace-pre-wrap">
{`{"query":"出箱投递怎么和 Redis Stream 解耦","evidence":[{"document_id":"<uuid>","chunk_index":0}]}`}
                </pre>
                <p>每行必须有非空 <code className="font-bold">query</code> 和非空 <code className="font-bold">evidence</code> 数组；每项证据仅认 <code className="font-bold">document_id</code> 与 <code className="font-bold">chunk_index</code>（≥0 的整数坐标），不可携带 quote 等多余键。</p>
              </div>

              {/* File selector */}
              <div>
                <input
                  type="file"
                  ref={fileInputRef}
                  accept=".jsonl"
                  onChange={(e) => {
                    const file = e.target.files?.[0] || null;
                    setSelectedFile(file);
                    setImportError(null);
                  }}
                  className="w-full text-xs text-slate-600 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-purple-50 file:text-purple-700 hover:file:bg-purple-100 cursor-pointer"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100 text-xs font-mono">
              <button
                type="button"
                onClick={() => setIsImportModalOpen(false)}
                className="px-3.5 py-1.5 rounded-lg text-slate-600 hover:bg-slate-100 transition-colors cursor-pointer"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleImportJsonl}
                disabled={importing || !selectedFile}
                className="flex items-center gap-1.5 px-4 py-1.5 bg-purple-600 hover:bg-purple-700 active:bg-purple-800 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-all cursor-pointer shadow-xs"
              >
                {importing ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>正在校验引文并入库...</span>
                  </>
                ) : (
                  <>
                    <UploadCloud className="w-3.5 h-3.5" />
                    <span>确认导入 (POST /items)</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Direct Create Empty TestSet Modal */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <Plus className="w-4 h-4 text-blue-600" />
                <h3 className="text-sm font-bold text-slate-900 font-mono">新建评测集</h3>
              </div>
              <button
                onClick={() => setIsCreateModalOpen(false)}
                className="text-slate-400 hover:text-slate-700 p-1 rounded-lg cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateEmptyTestSet} className="space-y-4 text-xs font-mono">
              <div>
                <label className="block text-slate-700 font-semibold mb-1.5">评测集名称 (可选)</label>
                <input
                  type="text"
                  maxLength={255}
                  value={newSetName}
                  onChange={(e) => setNewSetName(e.target.value)}
                  placeholder="留空自动生成默认名称（上限 255 字符）"
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-300 rounded-lg text-slate-900 placeholder-slate-400 focus:outline-none focus:border-blue-600 focus:ring-1 focus:ring-blue-100"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  className="px-3.5 py-1.5 rounded-lg text-slate-600 hover:bg-slate-100 transition-colors cursor-pointer"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={creatingSet}
                  className="flex items-center gap-1.5 px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition-all cursor-pointer shadow-xs disabled:opacity-50"
                >
                  {creatingSet ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>正在创建...</span>
                    </>
                  ) : (
                    <span>确认创建</span>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete TestSet Confirmation Modal */}
      {confirmDeleteSet && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-sm w-full p-5 shadow-xl space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-rose-50 border border-rose-200 flex items-center justify-center text-rose-600">
                <Trash2 className="w-4 h-4" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-slate-900 font-mono">确认删除评测集？</h3>
                <p className="text-xs text-slate-500 font-mono">该操作不可恢复</p>
              </div>
            </div>

            <p className="text-xs font-mono text-slate-600 bg-slate-50 p-3 rounded-lg border border-slate-200 break-all">
              评测集「{confirmDeleteSet.name}」及其名下所有题目、引文和运行记录将被级联删除。
            </p>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100 text-xs font-mono">
              <button
                onClick={() => setConfirmDeleteSet(null)}
                className="px-3 py-1.5 rounded-lg text-slate-600 hover:bg-slate-100 transition-colors cursor-pointer"
              >
                取消
              </button>
              <button
                onClick={() => executeDeleteTestSet(confirmDeleteSet)}
                disabled={deletingId === confirmDeleteSet.id}
                className="px-3.5 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white font-semibold shadow-xs transition-all cursor-pointer"
              >
                {deletingId === confirmDeleteSet.id ? '正在删除...' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Launch Run Modal */}
      {isLaunchRunModalOpen && selectedTestSet && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4 max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <Play className="w-4 h-4 text-blue-600 fill-current" />
                <h3 className="text-sm font-bold text-slate-900 font-mono">发起检索评测 (Run Evaluation)</h3>
              </div>
              <button
                onClick={() => setIsLaunchRunModalOpen(false)}
                className="text-slate-400 hover:text-slate-700 p-1 rounded-lg cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleStartRun} className="space-y-4 text-xs font-mono overflow-y-auto pr-1">
              <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl space-y-1 text-slate-700">
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">目标评测集:</span>
                  <strong className="text-slate-900">{selectedTestSet.name}</strong>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">评测题目数:</span>
                  <strong className="text-blue-700 font-bold">{selectedTestSet.item_count} 题</strong>
                </div>
              </div>

              <div>
                <label className="text-slate-700 font-medium block mb-1">
                  检索召回深度 Top-K: <span className="font-bold text-blue-600">{runTopK}</span>
                </label>
                <input
                  type="range"
                  min="1"
                  max="50"
                  value={runTopK}
                  onChange={(e) => setRunTopK(parseInt(e.target.value, 10))}
                  className="w-full accent-blue-600 cursor-pointer"
                />
              </div>

              <div className="space-y-2 pt-2 border-t border-slate-100">
                <label className="text-slate-700 font-semibold block">消融配方开关:</label>
                <div className="flex items-center justify-between p-2 rounded-lg border border-slate-200 bg-slate-50">
                  <span>查询改写 (Query Rewrite)</span>
                  <input
                    type="checkbox"
                    checked={runQueryRewrite}
                    onChange={(e) => setRunQueryRewrite(e.target.checked)}
                    className="rounded text-blue-600"
                  />
                </div>
                <div className="flex items-center justify-between p-2 rounded-lg border border-slate-200 bg-slate-50">
                  <span>生成式重排 (Reranker)</span>
                  <input
                    type="checkbox"
                    checked={runRerank}
                    onChange={(e) => setRunRerank(e.target.checked)}
                    className="rounded text-blue-600"
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setIsLaunchRunModalOpen(false)}
                  className="px-3.5 py-1.5 rounded-lg text-slate-600 hover:bg-slate-100 transition-colors cursor-pointer"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={launchingRun}
                  className="flex items-center gap-1.5 px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition-all cursor-pointer shadow-xs disabled:opacity-50"
                >
                  {launchingRun ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>正在启动...</span>
                    </>
                  ) : (
                    <span>启动评测 (POST /runs)</span>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Run Detail Modal */}
      {isRunDetailModalOpen && selectedRunDetail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-4xl w-full p-6 shadow-2xl max-h-[90vh] flex flex-col space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <Eye className="w-4 h-4 text-blue-600" />
                <h3 className="text-sm font-bold text-slate-900 font-mono">
                  评测运行打分明细 ({selectedRunDetail.id})
                </h3>
              </div>
              <button
                onClick={() => setIsRunDetailModalOpen(false)}
                className="text-slate-400 hover:text-slate-700 p-1 rounded-lg cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {loadingRunDetail ? (
              <div className="py-20 text-center text-slate-400 font-mono text-xs">
                <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2 text-blue-600" />
                正在加载运行打分明细...
              </div>
            ) : (
              <div className="flex-1 overflow-y-auto space-y-4 text-xs font-mono">
                {/* Metric banner */}
                {selectedRunDetail.metrics && (
                  <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl grid grid-cols-2 sm:grid-cols-4 gap-2">
                    <div>
                      <span className="text-slate-400 text-[10px] block">状态</span>
                      <strong className="text-slate-800 uppercase">{selectedRunDetail.status}</strong>
                    </div>
                    <div>
                      <span className="text-slate-400 text-[10px] block">Top-K</span>
                      <strong className="text-slate-800">{selectedRunDetail.config.top_k}</strong>
                    </div>
                    <div>
                      <span className="text-slate-400 text-[10px] block">平均延迟</span>
                      <strong className="text-slate-800">
                        {selectedRunDetail.metrics.avg_latency_ms ? `${Number(selectedRunDetail.metrics.avg_latency_ms).toFixed(1)} ms` : '—'}
                      </strong>
                    </div>
                    <div>
                      <span className="text-slate-400 text-[10px] block">题目数</span>
                      <strong className="text-slate-800">{selectedRunDetail.progress_total} 题</strong>
                    </div>
                  </div>
                )}

                {/* Items detail list */}
                {selectedRunDetail.items && selectedRunDetail.items.length > 0 ? (
                  <div className="space-y-3">
                    {selectedRunDetail.items.map((item, idx) => {
                      const attr = getItemAttribution(item);
                      return (
                        <div key={idx} className="p-3 bg-slate-50 rounded-xl border border-slate-200 space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="font-bold text-slate-700">题 #{idx + 1}</span>
                            <div className="flex items-center gap-2">
                              {attr.label && (
                                <span className={`px-2 py-0.5 rounded text-[10px] ${attr.badge}`}>
                                  {attr.label}
                                </span>
                              )}
                              <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                item.recall === 1 ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'
                              }`}>
                                {item.recall === 1 ? '全中 (Recall=1)' : '未全中 (Recall=0)'}
                              </span>
                            </div>
                          </div>
                          <div className="bg-white p-2.5 rounded border border-slate-200 font-semibold text-slate-900">
                            {item.query}
                          </div>
                          <div className="text-[11px] text-slate-500">
                            延迟: {item.latency_ms?.toFixed(1)} ms
                            {item.evidence_matched !== undefined && (
                              <span className="ml-2">命中证据: {item.evidence_matched} / {item.evidence_total}</span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="p-8 text-center text-slate-400">暂无逐题明细数据</div>
                )}
              </div>
            )}

            <div className="pt-2 border-t border-slate-100 flex justify-end">
              <button
                onClick={() => setIsRunDetailModalOpen(false)}
                className="px-4 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold rounded-lg text-xs font-mono cursor-pointer"
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
