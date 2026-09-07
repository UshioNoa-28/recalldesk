import React, { useState, useMemo } from 'react';
import { SearchHit, TargetChunkLink } from '../../types';
import { api, formatErrorMessage } from '../../api/client';
import { useToast } from '../../context/ToastContext';
import {
  Search,
  FileText,
  Copy,
  Check,
  Zap,
  Clock,
  ChevronDown,
  ChevronUp,
  Code2,
  Hash,
  Binary,
  Award,
  ExternalLink,
} from 'lucide-react';

interface QueryConsoleProps {
  onNavigateToChunk: (target: TargetChunkLink) => void;
}

export const QueryConsole: React.FC<QueryConsoleProps> = ({ onNavigateToChunk }) => {
  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState(5);
  const [loading, setLoading] = useState(false);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [searchedQuery, setSearchedQuery] = useState<string | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);
  const [viewRawJson, setViewRawJson] = useState(false);

  const { addToast } = useToast();

  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) {
      addToast('warning', '查询内容为空', '请输入需要检索的自然语言或关键词');
      return;
    }

    setLoading(true);
    const start = performance.now();
    try {
      const res = await api.search(trimmed, topK);
      const end = performance.now();
      setLatencyMs(Math.round(end - start));
      setHits(res.hits || []);
      setSearchedQuery(res.query || trimmed);
      if ((res.hits || []).length === 0) {
        addToast('info', '检索完成', '向量库中未匹配到相关切片');
      }
    } catch (err) {
      addToast('error', '检索失败', formatErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const handleCopyText = (text: string, index: number) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    addToast('info', '切片内容已复制');
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const uniqueDocs = useMemo(() => {
    const set = new Set(hits.map((h) => h.document_name));
    return Array.from(set);
  }, [hits]);

  const presetQueries = [
    '这个系统架构是怎么设计的？',
    'PostgreSQL 和 Qdrant 分别负责存储什么数据？',
    'Transactional Outbox 任务队列的工作流程',
    '如何启动与配置当前 RAG 服务？',
  ];

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-slate-50 overflow-y-auto">
      {/* Top Header Bar */}
      <div className="p-6 border-b border-slate-200 bg-white">
        <div className="max-w-5xl mx-auto space-y-4">
          <div>
            <h1 className="text-base font-bold text-slate-900 tracking-tight font-mono flex items-center gap-2">
              <Binary className="w-4 h-4 text-blue-600" />
              <span>向量检索控制台 (Vector Query Console)</span>
            </h1>
            <p className="text-xs text-slate-500 mt-0.5 font-mono">
              Qdrant 稠密向量 (1024-dim) + 服务端 BM25 稀疏混合检索与 RRF 融合排序
            </p>
          </div>

          {/* Query Bar */}
          <form onSubmit={handleSearch} className="flex items-center gap-2">
            <div className="relative flex-1">
              <div className="absolute left-3.5 top-1/2 -translate-y-1/2 flex items-center gap-1.5 text-slate-400 font-mono text-xs">
                <Search className="w-4 h-4 text-blue-600" />
              </div>
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="输入待检索自然语言问题 (例如：PostgreSQL 和 Qdrant 分别存什么？)..."
                className="w-full pl-10 pr-4 py-2.5 bg-white border border-slate-300 hover:border-slate-400 focus:border-blue-600 focus:ring-2 focus:ring-blue-100 rounded-lg text-xs font-mono text-slate-900 placeholder-slate-400 focus:outline-none transition-all shadow-2xs"
              />
            </div>

            {/* Top-K limit dropdown */}
            <div className="flex items-center gap-1.5 bg-white px-3 py-2.5 rounded-lg border border-slate-300 text-xs font-mono text-slate-600 shadow-2xs">
              <span className="text-slate-500">Top-K:</span>
              <select
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value))}
                className="bg-transparent text-blue-700 font-bold focus:outline-none cursor-pointer"
              >
                <option value={3}>3</option>
                <option value={5}>5</option>
                <option value={10}>10</option>
                <option value={20}>20</option>
              </select>
            </div>

            <button
              type="submit"
              disabled={loading || !query.trim()}
              className="flex items-center gap-1.5 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white rounded-lg text-xs font-semibold shadow-xs transition-all disabled:opacity-40 disabled:pointer-events-none cursor-pointer"
            >
              {loading ? (
                <>
                  <Zap className="w-3.5 h-3.5 animate-spin" />
                  <span>检索中...</span>
                </>
              ) : (
                <>
                  <Search className="w-3.5 h-3.5" />
                  <span>执行检索</span>
                </>
              )}
            </button>
          </form>

          {/* Quick Presets */}
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-slate-500 text-[11px] font-mono">快捷提问:</span>
              {presetQueries.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => setQuery(q)}
                  className="px-2.5 py-1 rounded-md bg-slate-100 hover:bg-slate-200 border border-slate-200 text-slate-700 text-[11px] font-mono transition-colors cursor-pointer"
                >
                  {q}
                </button>
              ))}
            </div>

            {latencyMs !== null && (
              <div className="flex items-center gap-1.5 font-mono text-[11px] text-slate-500">
                <Clock className="w-3.5 h-3.5 text-slate-400" />
                <span>检索耗时:</span>
                <span className="text-slate-900 font-bold">{latencyMs} ms</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Results Main Section */}
      <div className="flex-1 p-6">
        <div className="max-w-5xl mx-auto space-y-4">
          {searchedQuery !== null && (
            <div className="flex items-center justify-between text-xs font-mono text-slate-600 pb-2 border-b border-slate-200">
              <div className="flex items-center gap-3">
                <span>
                  Query: <strong className="text-slate-900">"{searchedQuery}"</strong>
                </span>
                <span>•</span>
                <span>
                  命中切片: <strong className="text-blue-700">{hits.length}</strong>
                </span>
                <span>•</span>
                <span>
                  关联文档: <strong className="text-emerald-700">{uniqueDocs.length}</strong>
                </span>
              </div>

              <button
                onClick={() => setViewRawJson(!viewRawJson)}
                className="flex items-center gap-1 text-slate-600 hover:text-blue-600 text-[11px] transition-colors cursor-pointer"
              >
                <Code2 className="w-3.5 h-3.5" />
                <span>{viewRawJson ? '切片卡片视图' : '查看原始 JSON'}</span>
              </button>
            </div>
          )}

          {viewRawJson ? (
            <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-xs">
              <pre className="text-xs font-mono text-slate-800 overflow-x-auto max-h-[600px]">
                {JSON.stringify({ query: searchedQuery, hits }, null, 2)}
              </pre>
            </div>
          ) : searchedQuery === null ? (
            <div className="bg-white border border-slate-200 rounded-xl p-16 text-center text-slate-500 space-y-3 shadow-xs">
              <div className="w-10 h-10 rounded-xl bg-blue-50 border border-blue-200 mx-auto flex items-center justify-center text-blue-600">
                <Search className="w-5 h-5" />
              </div>
              <p className="text-sm font-semibold text-slate-800 font-mono">输入查询语句开始检索</p>
              <p className="text-xs text-slate-500 max-w-md mx-auto leading-relaxed font-mono">
                系统将把查询向量化并在 Qdrant 向量库中进行混合检索与 RRF 融合。命中的切片点击直达链接可直接跳转至对应文档的切片位置。
              </p>
            </div>
          ) : hits.length === 0 ? (
            <div className="bg-white border border-slate-200 rounded-xl p-16 text-center text-slate-500 space-y-2 shadow-xs">
              <FileText className="w-8 h-8 mx-auto text-slate-400" />
              <p className="text-sm font-semibold text-slate-800 font-mono">未检索到匹配的切片</p>
              <p className="text-xs text-slate-500 font-mono">请尝试调整关键词，或在左侧上传相关文档。</p>
            </div>
          ) : (
            <div className="space-y-3">
              {hits.map((hit, index) => {
                const isExpanded = expandedIndex === index;
                const isVeryLong = hit.text.length > 280;
                const lineCount = hit.text.split('\n').length;
                const chunkNum =
                  hit.chunk_index !== undefined ? hit.chunk_index + 1 : 1;
                const docId = hit.document_id || '';
                const deepLinkHref = `#/documents/${docId}?chunk=${hit.chunk_index ?? 0}`;

                const handleDirectJump = (e: React.MouseEvent) => {
                  if (e.ctrlKey || e.metaKey) {
                    return;
                  }
                  e.preventDefault();
                  onNavigateToChunk({
                    documentId: hit.document_id || '',
                    chunkIndex: hit.chunk_index,
                    documentName: hit.document_name,
                    chunkText: hit.text,
                  });
                };

                return (
                  <div
                    key={index}
                    className="bg-white hover:bg-slate-50/70 border border-slate-200 hover:border-slate-300 rounded-xl p-4.5 space-y-3 transition-colors shadow-2xs"
                  >
                    {/* Clean Header Row: Rank, Document Name, Score, Jump Button, Copy Text */}
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-mono">
                      {/* Left: Clean, quiet document & chunk info */}
                      <div className="flex items-center gap-2 min-w-0 flex-wrap">
                        <span className="w-5 h-5 rounded bg-slate-100 border border-slate-200 flex items-center justify-center text-[10px] font-bold text-slate-700">
                          #{index + 1}
                        </span>

                        <div className="flex items-center gap-1.5 text-slate-800 font-medium text-xs truncate">
                          <FileText className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                          <span className="truncate max-w-xs sm:max-w-md font-semibold text-slate-900">
                            {hit.document_name}
                          </span>
                          <span className="text-slate-500 font-mono text-[11px]">
                            #chunk_{chunkNum}
                            {hit.chunk_count ? `/${hit.chunk_count}` : ''}
                          </span>
                        </div>

                        {hit.document_id && (
                          <span className="text-[10px] font-mono text-slate-400 flex items-center gap-0.5">
                            <Hash className="w-2.5 h-2.5" />
                            {hit.document_id.substring(0, 8)}
                          </span>
                        )}
                      </div>

                      {/* Right: Score + Clean Jump Button (in place of copy link) + Copy Text */}
                      <div className="flex items-center gap-1.5">
                        <span className="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-100 border border-slate-200 font-mono text-[11px] font-medium text-slate-700">
                          <Award className="w-3 h-3 text-blue-600" />
                          <span>RRF {hit.score.toFixed(4)}</span>
                        </span>

                        {/* Clean, unobtrusive Jump to Document button */}
                        <a
                          href={deepLinkHref}
                          onClick={handleDirectJump}
                          className="flex items-center gap-1 px-2.5 py-1 rounded bg-white hover:bg-blue-50 border border-slate-200 hover:border-blue-200 text-slate-600 hover:text-blue-600 text-[11px] font-mono transition-colors cursor-pointer shadow-2xs"
                          title="跳转至该文档及对应切片位置"
                        >
                          <ExternalLink className="w-3 h-3 text-slate-400" />
                          <span>查看文档</span>
                        </a>

                        {/* Copy Text Button */}
                        <button
                          onClick={() => handleCopyText(hit.text, index)}
                          className="p-1 rounded bg-white hover:bg-slate-100 border border-slate-200 text-slate-600 hover:text-slate-900 transition-colors cursor-pointer"
                          title="复制切片原文"
                        >
                          {copiedIndex === index ? (
                            <Check className="w-3.5 h-3.5 text-emerald-600" />
                          ) : (
                            <Copy className="w-3.5 h-3.5" />
                          )}
                        </button>
                      </div>
                    </div>

                    {/* Chunk Text Content */}
                    <div className="p-4 bg-slate-50 border border-slate-200 rounded-lg text-xs font-mono text-slate-900 leading-relaxed whitespace-pre-wrap break-words">
                      {isVeryLong && !isExpanded ? `${hit.text.slice(0, 280)}...` : hit.text}
                    </div>

                    {/* Footer Info */}
                    <div className="flex items-center justify-between text-[11px] font-mono text-slate-500 pt-0.5">
                      <span>
                        长度: {hit.text.length} 字符 • {lineCount} 行
                      </span>
                      {isVeryLong && (
                        <button
                          onClick={() => setExpandedIndex(isExpanded ? null : index)}
                          className="flex items-center gap-1 text-blue-600 hover:text-blue-700 font-medium transition-colors cursor-pointer"
                        >
                          {isExpanded ? (
                            <>
                              <ChevronUp className="w-3 h-3" />
                              <span>收起切片</span>
                            </>
                          ) : (
                            <>
                              <ChevronDown className="w-3 h-3" />
                              <span>展开全部切片内容</span>
                            </>
                          )}
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
