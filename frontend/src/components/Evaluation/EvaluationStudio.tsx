import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  TestSet,
  TestSetItem,
  TargetChunkLink,
  EvalRun,
} from '../../types';
import { api, formatErrorMessage } from '../../api/client';
import { useToast } from '../../context/ToastContext';
import {
  BarChart2,
  Sparkles,
  Trash2,
  FileText,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  RefreshCw,
  Layers,
  Hash,
  Copy,
  Check,
  Search,
  Plus,
  X,
  Play,
  TrendingUp,
  Eye,
} from 'lucide-react';

interface EvaluationStudioProps {
  selectedTestSetId?: string | null;
  onNavigateToChunk?: (target: TargetChunkLink) => void;
  onNavigateToExplorer?: () => void;
  onStartAppendChunks?: (testSet: { id: string; name: string }) => void;
  onUpdateTestSetCount?: (count: number) => void;
}

export const EvaluationStudio: React.FC<EvaluationStudioProps> = ({
  selectedTestSetId,
  onNavigateToChunk,
  onNavigateToExplorer,
  onStartAppendChunks,
  onUpdateTestSetCount,
}) => {
  const [testSets, setTestSets] = useState<TestSet[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedTestSet, setSelectedTestSet] = useState<TestSet | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [autoPolling, setAutoPolling] = useState(true);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [docMap, setDocMap] = useState<Record<string, string>>({});

  // Direct Create Modal in Studio
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [newSetName, setNewSetName] = useState('');
  const [creatingSet, setCreatingSet] = useState(false);

  // Eval Runs State
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [activeTab, setActiveTab] = useState<'items' | 'runs'>('items');
  const [isLaunchRunModalOpen, setIsLaunchRunModalOpen] = useState(false);
  const [runTopK, setRunTopK] = useState(5);
  const [launchingRun, setLaunchingRun] = useState(false);
  const [selectedRunDetail, setSelectedRunDetail] = useState<EvalRun | null>(null);
  const [loadingRunDetail, setLoadingRunDetail] = useState(false);
  const [isRunDetailModalOpen, setIsRunDetailModalOpen] = useState(false);
  const [runItemFilter, setRunItemFilter] = useState<'all' | 'missed' | 'hit'>('all');

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

  // Load document list once to map docId -> docName
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

  // Fetch Detail for Selected TestSet
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

  // Fetch Runs List for Selected TestSet
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

  // Fetch Run Detail (with per-query items)
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
      const run = await api.createRun(selectedTestSet.id, runTopK);
      addToast('success', '检索评测已启动', `正在评测 ${run.progress_total} 道题目...`);
      setIsLaunchRunModalOpen(false);
      setActiveTab('runs');
      await fetchRuns(selectedTestSet.id);
    } catch (err) {
      addToast('error', '发起评测失败', formatErrorMessage(err));
    } finally {
      setLaunchingRun(false);
    }
  };

  // Live polling for run detail modal if running
  useEffect(() => {
    if (isRunDetailModalOpen && selectedRunDetail && selectedRunDetail.status === 'running') {
      const timer = window.setInterval(() => {
        fetchRunDetail(selectedRunDetail.id, true);
      }, 2000);
      return () => clearInterval(timer);
    }
  }, [isRunDetailModalOpen, selectedRunDetail, fetchRunDetail]);

  // Fetch TestSets List
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

        // 1. Prioritize selectedTestSetId if it exists in current backend list
        if (selectedTestSetId && list.some((t) => t.id === selectedTestSetId)) {
          targetToLoad = selectedTestSetId;
        } else if (current && list.some((t) => t.id === current.id)) {
          // 2. Or retain current selection if it still exists
          targetToLoad = current.id;
        } else if (list.length > 0) {
          // 3. Fallback to first testset in list
          targetToLoad = list[0].id;
          if (selectedTestSetId && !list.some((t) => t.id === selectedTestSetId)) {
            // Clean up stale hash from URL without crashing
            window.location.hash = `#/evaluation/${list[0].id}`;
          }
        } else {
          // 4. Empty list
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

  // Auto polling for testsets in 'generating' status and runs in 'running' status
  useEffect(() => {
    if (autoPolling) {
      pollingTimerRef.current = window.setInterval(() => {
        const current = selectedTestSetRef.current;
        const currentRuns = runsRef.current;

        const hasGenerating =
          testSets.some((t) => t.status === 'generating') ||
          current?.status === 'generating';

        if (hasGenerating) {
          fetchTestSets(true);
          if (current) {
            fetchTestSetDetail(current.id, true);
          }
        }

        const hasRunningRun = currentRuns.some((r) => r.status === 'running');
        if (current && hasRunningRun) {
          fetchRuns(current.id, true);
        }
      }, 3000);
    }
    return () => {
      if (pollingTimerRef.current) clearInterval(pollingTimerRef.current);
    };
  }, [autoPolling, testSets, fetchTestSets, fetchTestSetDetail, fetchRuns]);

  const handleSelectTestSet = (ts: TestSet) => {
    setSelectedTestSet(ts);
    window.location.hash = `#/evaluation/${ts.id}`;
    fetchTestSetDetail(ts.id);
    fetchRuns(ts.id);
  };

  const handleDeleteTestSet = async (ts: TestSet) => {
    if (!window.confirm(`确定要删除评测集「${ts.name}」吗？`)) return;

    setDeletingId(ts.id);
    try {
      await api.deleteTestSet(ts.id);
      addToast('success', '评测集已删除', `「${ts.name}」已清除`);
      if (selectedTestSet?.id === ts.id) {
        setSelectedTestSet(null);
      }
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
      addToast('success', '评测集创建成功', `空评测集「${res.name}」已创建`);
      setIsCreateModalOpen(false);
      setNewSetName('');
      await fetchTestSets();
      setSelectedTestSet(res);
    } catch (err) {
      addToast('error', '创建评测集失败', formatErrorMessage(err));
    } finally {
      setCreatingSet(false);
    }
  };

  const handleCopy = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(key);
    setTimeout(() => setCopiedId(null), 2000);
    addToast('info', '已复制到剪贴板');
  };

  const getStatusBadge = (status: TestSet['status']) => {
    switch (status) {
      case 'ready':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
            <CheckCircle2 className="w-3 h-3" />
            READY
          </span>
        );
      case 'generating':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-amber-50 text-amber-700 border border-amber-200">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-ping" />
            GENERATING
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

  const getItemStatusBadge = (status: TestSetItem['status']) => {
    switch (status) {
      case 'ready':
        return (
          <span className="px-1.5 py-0.2 rounded text-[9px] font-mono font-bold bg-emerald-100 text-emerald-800 border border-emerald-200">
            READY
          </span>
        );
      case 'pending':
        return (
          <span className="px-1.5 py-0.2 rounded text-[9px] font-mono font-bold bg-amber-100 text-amber-800 border border-amber-200">
            PENDING
          </span>
        );
      case 'failed':
        return (
          <span className="px-1.5 py-0.2 rounded text-[9px] font-mono font-bold bg-rose-100 text-rose-800 border border-rose-200">
            FAILED
          </span>
        );
    }
  };

  const filteredTestSets = testSets.filter((t) => {
    const matchesSearch = t.name.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesStatus = statusFilter === 'all' || t.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  return (
    <div className="flex-1 flex flex-col md:flex-row min-h-0 bg-slate-50 overflow-hidden">
      {/* Left Master Pane: TestSets List */}
      <div className="w-full md:w-5/12 lg:w-4/12 border-r border-slate-200 flex flex-col bg-white min-h-0">
        {/* Top filter / search bar */}
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

          <div className="flex items-center gap-1.5">
            <div className="relative flex-1">
              <Search className="w-3 h-3 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="按名称过滤评测集..."
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
              <option value="ready">READY</option>
              <option value="generating">GENERATING</option>
              <option value="failed">FAILED</option>
            </select>
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
              {onNavigateToExplorer && (
                <button
                  onClick={onNavigateToExplorer}
                  className="text-blue-600 hover:underline inline-flex items-center gap-1 font-semibold"
                >
                  <Sparkles className="w-3 h-3" />
                  <span>前往【文档与切片】勾选出题</span>
                </button>
              )}
            </div>
          ) : (
            filteredTestSets.map((ts) => {
              const isSelected = selectedTestSet?.id === ts.id;
              const percent =
                ts.progress_total > 0
                  ? Math.round((ts.progress_done / ts.progress_total) * 100)
                  : 0;

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
                      <span className="text-xs font-mono text-slate-900 font-semibold truncate">
                        {ts.name}
                      </span>
                    </div>
                    {getStatusBadge(ts.status)}
                  </div>

                  {/* Progress & Items Info */}
                  <div className="mt-2 space-y-1.5 text-[11px] font-mono text-slate-500">
                    <div className="flex items-center justify-between">
                      <span>
                        出题进度: {ts.progress_done} / {ts.progress_total} 题 ({percent}%)
                      </span>
                      <span>
                        {ts.created_at
                          ? new Date(ts.created_at).toLocaleTimeString('zh-CN', {
                              hour: '2-digit',
                              minute: '2-digit',
                            })
                          : '—'}
                      </span>
                    </div>

                    {/* Progress mini bar */}
                    <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                      <div
                        className={`h-full transition-all duration-300 ${
                          ts.status === 'ready'
                            ? 'bg-emerald-500'
                            : ts.status === 'failed'
                            ? 'bg-rose-500'
                            : 'bg-blue-600'
                        }`}
                        style={{ width: `${percent}%` }}
                      />
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Quick action footer */}
        {onNavigateToExplorer && (
          <div className="p-3 border-t border-slate-200 bg-slate-50">
            <button
              onClick={onNavigateToExplorer}
              className="w-full flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg bg-white hover:bg-slate-100 border border-slate-200 text-blue-700 text-xs font-mono font-semibold transition-colors cursor-pointer shadow-2xs"
            >
              <Sparkles className="w-3.5 h-3.5 text-blue-600" />
              <span>从文档切片勾选新建评测集 ➔</span>
            </button>
          </div>
        )}
      </div>

      {/* Right Detail Pane: Selected TestSet & Items */}
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
                  {getStatusBadge(selectedTestSet.status)}

                  {/* Launch Run Button */}
                  <button
                    onClick={() => setIsLaunchRunModalOpen(true)}
                    disabled={selectedTestSet.progress_done === 0 || runs.some((r) => r.status === 'running')}
                    className="flex items-center gap-1.5 px-3 py-1 text-xs font-mono font-bold text-white bg-blue-600 hover:bg-blue-700 active:bg-blue-800 disabled:bg-slate-300 disabled:cursor-not-allowed rounded-md transition-colors cursor-pointer shadow-xs"
                    title={
                      selectedTestSet.progress_done === 0
                        ? '需至少有 1 道出题完成的题目方可发起评测'
                        : runs.some((r) => r.status === 'running')
                        ? '当前已有评测运行正在执行中'
                        : '对当前已就绪的题目发起多路召回与指标评估'
                    }
                  >
                    <Play className="w-3.5 h-3.5 fill-current" />
                    <span>发起评测</span>
                  </button>

                  {/* Add items navigation button */}
                  {(onStartAppendChunks || onNavigateToExplorer) && (
                    <button
                      onClick={() => {
                        if (onStartAppendChunks) {
                          onStartAppendChunks({ id: selectedTestSet.id, name: selectedTestSet.name });
                        } else if (onNavigateToExplorer) {
                          onNavigateToExplorer();
                        }
                      }}
                      className="flex items-center gap-1 px-2.5 py-1 text-xs font-mono text-blue-700 hover:text-blue-800 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-md transition-colors cursor-pointer"
                      title={`前往文档切片勾选切片，追加至「${selectedTestSet.name}」`}
                    >
                      <Plus className="w-3.5 h-3.5" />
                      <span>追加切片</span>
                    </button>
                  )}

                  {/* Delete TestSet Button */}
                  <button
                    onClick={() => handleDeleteTestSet(selectedTestSet)}
                    disabled={deletingId === selectedTestSet.id}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs font-mono text-rose-600 hover:text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 rounded-md transition-colors cursor-pointer disabled:opacity-50"
                    title="删除评测集及其所有题目"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>{deletingId === selectedTestSet.id ? '删除中...' : '删除评测集'}</span>
                  </button>
                </div>
              </div>

              {/* Error Message banner if failed */}
              {selectedTestSet.error_message && (
                <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-xs font-mono text-rose-700 flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0 text-rose-600 mt-0.5" />
                  <div>
                    <span className="font-bold">失败信息:</span> {selectedTestSet.error_message}
                  </div>
                </div>
              )}

              {/* Progress Overview Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-3 border-t border-slate-100 text-xs font-mono">
                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <span className="text-slate-500 text-[10px] block mb-0.5">题目总数 (TOTAL)</span>
                  <span className="text-blue-700 font-bold text-base">
                    {selectedTestSet.progress_total || (selectedTestSet.items ? selectedTestSet.items.length : 0)} 题
                  </span>
                </div>

                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <span className="text-slate-500 text-[10px] block mb-0.5">出题完成度</span>
                  <span className="text-emerald-700 font-bold text-base">
                    {selectedTestSet.progress_done} / {selectedTestSet.progress_total}
                  </span>
                </div>

                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <span className="text-slate-500 text-[10px] block mb-0.5">历史评测运行</span>
                  <span className="text-purple-700 font-bold text-base">
                    {runs.length} 次
                  </span>
                </div>

                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <span className="text-slate-500 text-[10px] block mb-0.5">出题模式</span>
                  <span className="text-slate-800 text-[11px] truncate block font-medium">
                    LLM Worker 异步出题
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
                <span>题目明细 ({selectedTestSet.items ? selectedTestSet.items.length : selectedTestSet.progress_total})</span>
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

            {/* Tab 1: TestSet Items List (Questions) */}
            {activeTab === 'items' ? (
              <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-4 shadow-xs">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-mono">
                  <div className="flex items-center gap-1.5 text-slate-900 font-bold">
                    <FileText className="w-4 h-4 text-blue-600" />
                    <span>
                      题目明细列表 ({selectedTestSet.items ? selectedTestSet.items.length : selectedTestSet.progress_total} 题)
                    </span>
                  </div>

                  <span className="text-[11px] text-slate-400">
                    基于切片内容生成的自然语言测试问题
                  </span>
                </div>

                {/* Items Stream */}
                {loadingDetail ? (
                  <div className="p-8 text-center text-slate-400 font-mono text-xs">
                    <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-blue-600" />
                    正在加载题目详情...
                  </div>
                ) : selectedTestSet.items && selectedTestSet.items.length > 0 ? (
                  <div className="space-y-3">
                    {selectedTestSet.items.map((item, idx) => {
                      const docName =
                        item.document_name ||
                        docMap[item.answer_document_id] ||
                        `文档 ${item.answer_document_id.substring(0, 8)}...`;

                      return (
                        <div
                          key={item.id || idx}
                          className="p-4 bg-slate-50/70 border border-slate-200 rounded-xl space-y-3 hover:border-slate-300 transition-colors"
                        >
                          {/* Item Header */}
                          <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-200/80 text-xs font-mono">
                            <div className="flex items-center gap-2 min-w-0">
                              <span className="w-5 h-5 rounded bg-white border border-slate-200 flex items-center justify-center text-[10px] font-bold text-slate-700">
                                #{idx + 1}
                              </span>

                              <div className="flex items-center gap-1.5 text-slate-800 font-medium truncate">
                                <span className="text-slate-400">出题源:</span>
                                <strong className="text-slate-900 truncate" title={docName}>
                                  {docName}
                                </strong>
                                <span className="text-blue-700 font-bold">
                                  #chunk_{item.answer_chunk_index + 1}
                                </span>
                              </div>

                              {getItemStatusBadge(item.status)}
                            </div>

                            {onNavigateToChunk && (
                              <button
                                onClick={() =>
                                  onNavigateToChunk({
                                    documentId: item.answer_document_id,
                                    chunkIndex: item.answer_chunk_index,
                                    documentName: docName,
                                  })
                                }
                                className="flex items-center gap-1 px-2 py-0.5 rounded bg-white hover:bg-slate-100 border border-slate-200 text-slate-600 text-[11px] transition-colors cursor-pointer"
                                title="在文档浏览器中定位该切片"
                              >
                                <ExternalLink className="w-3 h-3 text-slate-400" />
                                <span>查看切片</span>
                              </button>
                            )}
                          </div>

                          {/* Generated Question */}
                          {item.query ? (
                            <div className="p-3 bg-white border border-slate-200 rounded-lg text-xs font-mono text-slate-900 leading-relaxed font-semibold">
                              {item.query}
                            </div>
                          ) : item.status === 'failed' ? (
                            <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-xs font-mono text-rose-700">
                              ⚠️ 出题失败: {item.error_message || '未知错误'}
                            </div>
                          ) : (
                            <div className="p-3 bg-amber-50/60 border border-amber-200/80 rounded-lg text-xs font-mono text-amber-800 flex items-center gap-2">
                              <RefreshCw className="w-3.5 h-3.5 animate-spin text-amber-600" />
                              <span>LLM Worker 正在分析切片语义并生成自然语言提问...</span>
                            </div>
                          )}

                          {/* Ground Truth Coordinate Info */}
                          <div className="text-[11px] font-mono text-slate-400 flex items-center gap-3">
                            <span className="flex items-center gap-1">
                              <Hash className="w-3 h-3" />
                              <span>Doc ID: {item.answer_document_id}</span>
                            </span>
                            <span>•</span>
                            <span>Chunk Index: #{item.answer_chunk_index}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="p-12 text-center text-slate-400 font-mono text-xs space-y-3">
                    <Layers className="w-8 h-8 mx-auto text-slate-300" />
                    <p>当前评测集暂无题目</p>
                    {(onStartAppendChunks || onNavigateToExplorer) && (
                      <button
                        onClick={() => {
                          if (onStartAppendChunks) {
                            onStartAppendChunks({ id: selectedTestSet.id, name: selectedTestSet.name });
                          } else if (onNavigateToExplorer) {
                            onNavigateToExplorer();
                          }
                        }}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-semibold font-mono transition-colors cursor-pointer"
                      >
                        <Sparkles className="w-3.5 h-3.5" />
                        <span>前往【文档与切片】勾选切片添加 ➔</span>
                      </button>
                    )}
                  </div>
                )}
              </div>
            ) : (
              /* Tab 2: Evaluation Runs List */
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
                      disabled={selectedTestSet.progress_done === 0 || runs.some((r) => r.status === 'running')}
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
                        点击「发起评测」按钮，系统将自动使用已就绪的题目测试检索召回率 (Recall@K) 与平均倒数排名 (MRR)。
                      </p>
                    </div>
                    {selectedTestSet.progress_done > 0 && (
                      <button
                        onClick={() => setIsLaunchRunModalOpen(true)}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-semibold font-mono transition-colors cursor-pointer shadow-xs"
                      >
                        <Play className="w-3.5 h-3.5 fill-current" />
                        <span>立即发起首次评测 ➔</span>
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="space-y-4">
                    {runs.map((run, idx) => {
                      const k = run.config.top_k || 5;
                      const recallKey = `recall@${k}`;
                      const recallVal = run.metrics && recallKey in run.metrics ? run.metrics[recallKey] : null;
                      const mrrVal = run.metrics?.mrr;
                      const latencyVal = run.metrics?.avg_latency_ms;
                      const queriesVal = run.metrics?.queries || run.progress_total;

                      return (
                        <div
                          key={run.id}
                          className={`p-4 rounded-xl border transition-all ${
                            run.status === 'running'
                              ? 'bg-amber-50/40 border-amber-300 shadow-sm'
                              : 'bg-slate-50/70 border-slate-200 hover:border-slate-300'
                          }`}
                        >
                          {/* Run Card Header */}
                          <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-200/80 text-xs font-mono">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="w-5 h-5 rounded bg-white border border-slate-200 flex items-center justify-center text-[10px] font-bold text-slate-700">
                                #{runs.length - idx}
                              </span>

                              {/* Status Badge */}
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
                              {run.config.query_rewrite && (
                                <span className="px-1.5 py-0.5 rounded text-[10px] bg-purple-100 text-purple-700 font-mono">
                                  启用了查询改写
                                </span>
                              )}
                            </div>

                            <div className="flex items-center gap-3">
                              <span className="text-[11px] text-slate-400">
                                {run.created_at ? new Date(run.created_at).toLocaleString('zh-CN') : '—'}
                              </span>

                              <button
                                onClick={() => handleOpenRunDetail(run)}
                                className="flex items-center gap-1 px-2.5 py-1 rounded bg-white hover:bg-slate-100 border border-slate-200 text-blue-700 text-xs font-semibold transition-colors cursor-pointer shadow-2xs"
                              >
                                <Eye className="w-3.5 h-3.5 text-blue-600" />
                                <span>查看打分明细 ➔</span>
                              </button>
                            </div>
                          </div>

                          {/* Progress bar if running */}
                          {run.status === 'running' && (
                            <div className="mt-3 space-y-1">
                              <div className="flex items-center justify-between text-[11px] font-mono text-amber-800">
                                <span>评测进度</span>
                                <span>
                                  {run.progress_done} / {run.progress_total} 题 (
                                  {run.progress_total > 0
                                    ? Math.round((run.progress_done / run.progress_total) * 100)
                                    : 0}
                                  %)
                                </span>
                              </div>
                              <div className="w-full h-1.5 bg-amber-100 rounded-full overflow-hidden">
                                <div
                                  className="h-full bg-amber-500 rounded-full transition-all duration-300"
                                  style={{
                                    width: `${
                                      run.progress_total > 0
                                        ? (run.progress_done / run.progress_total) * 100
                                        : 0
                                    }%`,
                                  }}
                                />
                              </div>
                            </div>
                          )}

                          {/* Metrics Grid */}
                          {run.metrics && (
                            <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs font-mono">
                              <div className="p-2.5 bg-white rounded-lg border border-slate-200/90 shadow-2xs">
                                <span className="text-slate-400 text-[10px] block mb-0.5">
                                  召回率 ({recallKey})
                                </span>
                                <span className="text-emerald-700 font-bold text-sm">
                                  {recallVal !== null && recallVal !== undefined
                                    ? `${(recallVal * 100).toFixed(1)}%`
                                    : '—'}
                                </span>
                              </div>

                              <div className="p-2.5 bg-white rounded-lg border border-slate-200/90 shadow-2xs">
                                <span className="text-slate-400 text-[10px] block mb-0.5">
                                  倒数排名 (MRR)
                                </span>
                                <span className="text-blue-700 font-bold text-sm">
                                  {mrrVal !== null && mrrVal !== undefined ? mrrVal.toFixed(4) : '—'}
                                </span>
                              </div>

                              <div className="p-2.5 bg-white rounded-lg border border-slate-200/90 shadow-2xs">
                                <span className="text-slate-400 text-[10px] block mb-0.5">
                                  平均检索延迟
                                </span>
                                <span className="text-slate-800 font-bold text-sm">
                                  {latencyVal !== null && latencyVal !== undefined
                                    ? `${latencyVal} ms`
                                    : '—'}
                                </span>
                              </div>

                              <div className="p-2.5 bg-white rounded-lg border border-slate-200/90 shadow-2xs">
                                <span className="text-slate-400 text-[10px] block mb-0.5">
                                  评测样本量
                                </span>
                                <span className="text-slate-700 font-bold text-sm">
                                  {queriesVal} 题
                                </span>
                              </div>
                            </div>
                          )}

                          {run.error_message && (
                            <div className="mt-3 p-2.5 bg-rose-50 border border-rose-200 rounded-lg text-xs font-mono text-rose-700">
                              <strong>评测异常:</strong> {run.error_message}
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
            <p>请在左侧列表中选择一个评测集查看其题目与出题进度</p>
          </div>
        )}
      </div>

      {/* Launch Run Modal */}
      {isLaunchRunModalOpen && selectedTestSet && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-4 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <Play className="w-4 h-4 text-blue-600 fill-current" />
                <h3 className="text-sm font-bold text-slate-900 font-mono">
                  发起检索评测 (Run Evaluation)
                </h3>
              </div>
              <button
                onClick={() => setIsLaunchRunModalOpen(false)}
                className="text-slate-400 hover:text-slate-700 p-1 rounded-lg cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleStartRun} className="space-y-4 text-xs font-mono">
              <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl space-y-1.5 text-slate-700">
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">目标评测集:</span>
                  <strong className="text-slate-900">{selectedTestSet.name}</strong>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">可用题目数:</span>
                  <strong className="text-emerald-700 font-bold">{selectedTestSet.progress_done} 题</strong>
                </div>
              </div>

              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <label className="text-slate-700 font-medium">
                    检索召回深度 (Top-K):
                  </label>
                  <div className="flex items-center gap-1.5 font-mono">
                    <span className="text-xs text-slate-400">前</span>
                    <input
                      type="number"
                      min={1}
                      max={50}
                      value={runTopK}
                      onChange={(e) => {
                        const val = parseInt(e.target.value, 10);
                        if (!isNaN(val)) {
                          setRunTopK(Math.max(1, Math.min(50, val)));
                        }
                      }}
                      className="w-14 px-2 py-1 text-center font-bold text-blue-700 bg-blue-50 border border-blue-200 rounded-md focus:outline-none focus:border-blue-600 text-xs"
                    />
                    <span className="text-xs text-slate-400">名</span>
                  </div>
                </div>

                {/* Continuous Range Slider */}
                <div className="space-y-1.5 pt-1">
                  <input
                    type="range"
                    min="1"
                    max="50"
                    value={runTopK}
                    onChange={(e) => setRunTopK(parseInt(e.target.value, 10))}
                    className="w-full accent-blue-600 cursor-pointer"
                  />
                  <div className="flex justify-between text-[10px] text-slate-400 font-mono">
                    <span>1</span>
                    <span className="text-blue-600 font-semibold">Top-{runTopK}</span>
                    <span>50</span>
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setIsLaunchRunModalOpen(false)}
                  className="px-3.5 py-1.5 text-slate-600 hover:bg-slate-100 rounded-lg cursor-pointer"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={launchingRun}
                  className="flex items-center gap-1.5 px-4 py-1.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white font-semibold rounded-lg shadow-xs disabled:opacity-50 cursor-pointer"
                >
                  {launchingRun ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>正在启动评测...</span>
                    </>
                  ) : (
                    <>
                      <Play className="w-3.5 h-3.5 fill-current" />
                      <span>开始评测 (Top-{runTopK})</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Run Detail Modal with Per-Query Breakdown */}
      {isRunDetailModalOpen && selectedRunDetail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-4xl w-full p-6 shadow-2xl flex flex-col max-h-[88vh] space-y-4 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <TrendingUp className="w-5 h-5 text-blue-600" />
                <h3 className="text-sm font-bold text-slate-900 font-mono">
                  评测运行打分明细 - Top-{selectedRunDetail.config?.top_k || 5}
                </h3>
              </div>
              <button
                onClick={() => setIsRunDetailModalOpen(false)}
                className="text-slate-400 hover:text-slate-700 p-1 rounded-lg cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Metrics Overview in Modal */}
            {selectedRunDetail.metrics && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs font-mono">
                <div className="p-3 bg-emerald-50/70 border border-emerald-200 rounded-xl">
                  <span className="text-emerald-800 text-[10px] block mb-0.5">
                    Recall@{selectedRunDetail.config?.top_k || 5} (召回率)
                  </span>
                  <span className="text-emerald-700 font-bold text-lg">
                    {selectedRunDetail.metrics[`recall@${selectedRunDetail.config?.top_k || 5}`] !== undefined
                      ? `${(Number(selectedRunDetail.metrics[`recall@${selectedRunDetail.config?.top_k || 5}`]) * 100).toFixed(1)}%`
                      : '—'}
                  </span>
                </div>

                <div className="p-3 bg-blue-50/70 border border-blue-200 rounded-xl">
                  <span className="text-blue-800 text-[10px] block mb-0.5">
                    MRR (平均倒数排名)
                  </span>
                  <span className="text-blue-700 font-bold text-lg">
                    {selectedRunDetail.metrics.mrr !== undefined ? Number(selectedRunDetail.metrics.mrr).toFixed(4) : '—'}
                  </span>
                </div>

                <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl">
                  <span className="text-slate-500 text-[10px] block mb-0.5">
                    平均检索延迟
                  </span>
                  <span className="text-slate-800 font-bold text-lg">
                    {selectedRunDetail.metrics.avg_latency_ms} ms
                  </span>
                </div>

                <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl">
                  <span className="text-slate-500 text-[10px] block mb-0.5">
                    打分题量
                  </span>
                  <span className="text-slate-800 font-bold text-lg">
                    {selectedRunDetail.metrics.queries || selectedRunDetail.items?.length || 0} 题
                  </span>
                </div>
              </div>
            )}

            {/* Filter Tabs in Modal */}
            <div className="flex items-center justify-between gap-2 border-b border-slate-100 pb-2 text-xs font-mono">
              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => setRunItemFilter('all')}
                  className={`px-2.5 py-1 rounded-md transition-colors cursor-pointer ${
                    runItemFilter === 'all'
                      ? 'bg-blue-600 text-white font-semibold'
                      : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  全部 ({selectedRunDetail.items ? selectedRunDetail.items.length : 0})
                </button>
                <button
                  onClick={() => setRunItemFilter('missed')}
                  className={`px-2.5 py-1 rounded-md transition-colors cursor-pointer ${
                    runItemFilter === 'missed'
                      ? 'bg-rose-600 text-white font-semibold'
                      : 'bg-rose-50 text-rose-700 hover:bg-rose-100'
                  }`}
                >
                  未召回 ({selectedRunDetail.items ? selectedRunDetail.items.filter((i) => i.low_recall).length : 0})
                </button>
                <button
                  onClick={() => setRunItemFilter('hit')}
                  className={`px-2.5 py-1 rounded-md transition-colors cursor-pointer ${
                    runItemFilter === 'hit'
                      ? 'bg-emerald-600 text-white font-semibold'
                      : 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                  }`}
                >
                  切片命中 ({selectedRunDetail.items ? selectedRunDetail.items.filter((i) => i.hit_rank !== null).length : 0})
                </button>
              </div>

              {selectedRunDetail.status === 'running' && (
                <div className="flex items-center gap-1.5 text-amber-700 text-[11px]">
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  <span>实时打分中...</span>
                </div>
              )}
            </div>

            {/* Questions Table / List */}
            <div className="flex-1 overflow-y-auto space-y-3 pr-1">
              {loadingRunDetail ? (
                <div className="p-12 text-center text-slate-400 font-mono text-xs">
                  <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-blue-600" />
                  正在加载逐题结果...
                </div>
              ) : selectedRunDetail.items && selectedRunDetail.items.length > 0 ? (
                selectedRunDetail.items
                  .filter((item) => {
                    if (runItemFilter === 'missed') return item.low_recall;
                    if (runItemFilter === 'hit') return item.hit_rank !== null;
                    return true;
                  })
                  .map((item, idx) => {
                    const docName =
                      docMap[item.answer_document_id] ||
                      `文档 ${item.answer_document_id.substring(0, 8)}...`;

                    return (
                      <div
                        key={item.testset_item_id || idx}
                        className={`p-3.5 rounded-xl border text-xs font-mono space-y-2 transition-colors ${
                          item.low_recall
                            ? 'bg-rose-50/40 border-rose-200'
                            : item.hit_rank === 1
                            ? 'bg-emerald-50/30 border-emerald-200'
                            : 'bg-slate-50/70 border-slate-200'
                        }`}
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className="w-5 h-5 rounded bg-white border border-slate-200 flex items-center justify-center text-[10px] font-bold text-slate-600">
                              #{idx + 1}
                            </span>

                            {/* Recall status */}
                            {item.recall === 1 ? (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-200">
                                <Check className="w-3 h-3 text-emerald-600" />
                                文档已召回
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-rose-100 text-rose-800 border border-rose-200">
                                <X className="w-3 h-3 text-rose-600" />
                                文档未召回
                              </span>
                            )}

                            {/* Hit Rank */}
                            {item.hit_rank !== null ? (
                              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-100 text-blue-800 border border-blue-200">
                                切片命中名次: #{item.hit_rank}
                              </span>
                            ) : (
                              <span className="px-2 py-0.5 rounded text-[10px] text-slate-400 bg-slate-100 border border-slate-200">
                                切片未入前 K
                              </span>
                            )}

                            <span className="text-[11px] text-slate-500">
                              MRR: {item.mrr ? Number(item.mrr).toFixed(3) : '0.000'}
                            </span>

                            <span className="text-[11px] text-slate-400">
                              耗时: {Number(item.latency_ms).toFixed(1)} ms
                            </span>
                          </div>

                          {onNavigateToChunk && (
                            <button
                              onClick={() => {
                                setIsRunDetailModalOpen(false);
                                onNavigateToChunk({
                                  documentId: item.answer_document_id,
                                  chunkIndex: item.answer_chunk_index,
                                  documentName: docName,
                                });
                              }}
                              className="flex items-center gap-1 px-2 py-0.5 rounded bg-white hover:bg-slate-100 border border-slate-200 text-blue-700 text-[11px] transition-colors cursor-pointer"
                            >
                              <ExternalLink className="w-3 h-3 text-blue-500" />
                              <span>定位目标切片</span>
                            </button>
                          )}
                        </div>

                        {/* Query Text */}
                        <div className="p-2.5 bg-white border border-slate-200 rounded-lg text-slate-900 font-semibold leading-relaxed">
                          {item.query}
                        </div>

                        {/* Target Ground Truth Coordinates */}
                        <div className="text-[11px] text-slate-500 flex items-center gap-2">
                          <span>出题目标源:</span>
                          <strong className="text-slate-800">{docName}</strong>
                          <span className="text-blue-700 font-bold">
                            #chunk_{item.answer_chunk_index + 1}
                          </span>
                        </div>
                      </div>
                    );
                  })
              ) : (
                <div className="p-8 text-center text-slate-400 font-mono text-xs">
                  暂无题目打分数据
                </div>
              )}
            </div>

            <div className="flex items-center justify-end pt-2 border-t border-slate-100">
              <button
                onClick={() => setIsRunDetailModalOpen(false)}
                className="px-4 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded-lg cursor-pointer"
              >
                关闭
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
                <BarChart2 className="w-5 h-5 text-blue-600" />
                <h3 className="text-sm font-bold text-slate-900 font-mono">
                  新建空评测集
                </h3>
              </div>
              <button
                onClick={() => setIsCreateModalOpen(false)}
                className="text-slate-400 hover:text-slate-700 p-1 rounded-lg cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateEmptyTestSet} className="space-y-4 text-xs font-mono">
              <div className="space-y-1.5">
                <label className="text-slate-700 font-medium block">
                  评测集名称 (可选)
                </label>
                <input
                  type="text"
                  value={newSetName}
                  onChange={(e) => setNewSetName(e.target.value)}
                  placeholder="例如：多文档召回测试集"
                  className="w-full p-2.5 bg-slate-50 border border-slate-300 rounded-lg text-slate-900 focus:outline-none focus:border-blue-600 focus:bg-white"
                />
              </div>

              <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-[11px] text-slate-600 leading-relaxed">
                创建后，可在【文档与切片】页面勾选任意文档的切片批量加入该测试集。
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  className="px-3 py-1.5 text-slate-600 hover:bg-slate-100 rounded-lg cursor-pointer"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={creatingSet}
                  className="flex items-center gap-1.5 px-4 py-1.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white font-semibold rounded-lg shadow-xs disabled:opacity-50 cursor-pointer"
                >
                  {creatingSet ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>正在创建...</span>
                    </>
                  ) : (
                    <>
                      <Plus className="w-3.5 h-3.5" />
                      <span>确认创建 (POST /eval/testsets)</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
