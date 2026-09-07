import React from 'react';
import { ActiveView, HealthResponse } from '../types';
import {
  Search,
  Database,
  Plus,
  Settings,
  RefreshCw,
  Cpu,
  Layers,
  BarChart2,
} from 'lucide-react';

interface SidebarProps {
  activeView: ActiveView;
  setActiveView: (view: ActiveView) => void;
  health: HealthResponse | null;
  healthLoading: boolean;
  onRefreshHealth: () => void;
  onOpenSettings: () => void;
  onOpenUpload: () => void;
  documentCount: number;
  evalQuestionCount?: number;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeView,
  setActiveView,
  health,
  healthLoading,
  onRefreshHealth,
  onOpenSettings,
  onOpenUpload,
  documentCount,
  evalQuestionCount = 0,
}) => {
  const isHealthy = health?.status === 'ok';

  return (
    <aside className="w-64 shrink-0 flex flex-col light-sidebar h-screen select-none bg-white border-r border-slate-200">
      {/* Brand Header */}
      <div className="p-4 border-b border-slate-200 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-50 border border-blue-200 flex items-center justify-center text-blue-600 shadow-xs">
            <Layers className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-bold tracking-tight text-slate-900 font-mono">
                RecallDesk
              </span>
              <span className="px-1.5 py-0.2 text-[9px] font-mono font-bold text-blue-700 bg-blue-50 rounded border border-blue-200 uppercase">
                Studio
              </span>
            </div>
            <p className="text-[11px] text-slate-500 font-mono">Vector &amp; Chunks Hub</p>
          </div>
        </div>
      </div>

      {/* Primary Action: Upload */}
      <div className="p-3">
        <button
          onClick={onOpenUpload}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white rounded-lg text-xs font-semibold shadow-xs transition-all cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          <span>上传知识库文档</span>
        </button>
      </div>

      {/* Navigation Menu */}
      <nav className="flex-1 px-3 py-2 space-y-1 overflow-y-auto text-xs font-mono">
        <div className="px-2 py-1.5 text-[10px] text-slate-400 tracking-wider uppercase font-bold">
          Workspace
        </div>

        {/* Vector Search item */}
        <button
          onClick={() => setActiveView('search')}
          className={`w-full flex items-center justify-between px-3 py-2 rounded-lg font-medium transition-colors cursor-pointer ${
            activeView === 'search'
              ? 'bg-blue-50 text-blue-700 font-semibold border border-blue-200 shadow-xs'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
          }`}
        >
          <div className="flex items-center gap-2.5">
            <Search className={`w-4 h-4 ${activeView === 'search' ? 'text-blue-600' : 'text-slate-400'}`} />
            <span>向量检索 (Search)</span>
          </div>
        </button>

        {/* Document Explorer item */}
        <button
          onClick={() => setActiveView('documents')}
          className={`w-full flex items-center justify-between px-3 py-2 rounded-lg font-medium transition-colors cursor-pointer ${
            activeView === 'documents'
              ? 'bg-blue-50 text-blue-700 font-semibold border border-blue-200 shadow-xs'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
          }`}
        >
          <div className="flex items-center gap-2.5">
            <Database className={`w-4 h-4 ${activeView === 'documents' ? 'text-blue-600' : 'text-slate-400'}`} />
            <span>文档与切片 (Chunks)</span>
          </div>

          {documentCount > 0 && (
            <span className="px-1.5 py-0.5 rounded-md text-[10px] bg-slate-100 text-slate-600 border border-slate-200">
              {documentCount}
            </span>
          )}
        </button>

        {/* Evaluation Studio item */}
        <button
          onClick={() => setActiveView('evaluation')}
          className={`w-full flex items-center justify-between px-3 py-2 rounded-lg font-medium transition-colors cursor-pointer ${
            activeView === 'evaluation'
              ? 'bg-blue-50 text-blue-700 font-semibold border border-blue-200 shadow-xs'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
          }`}
        >
          <div className="flex items-center gap-2.5">
            <BarChart2 className={`w-4 h-4 ${activeView === 'evaluation' ? 'text-blue-600' : 'text-slate-400'}`} />
            <span>切片评测中心 (Eval)</span>
          </div>

          {evalQuestionCount > 0 && (
            <span className="px-1.5 py-0.5 rounded-md text-[10px] bg-blue-100 text-blue-700 border border-blue-200 font-bold">
              {evalQuestionCount}
            </span>
          )}
        </button>
      </nav>

      {/* Vector Specs Badge */}
      <div className="px-3 py-2.5 text-[11px] font-mono text-slate-500 space-y-1.5 border-t border-slate-200 bg-slate-50">
        <div className="flex items-center justify-between text-[10px]">
          <span className="flex items-center gap-1 text-slate-600">
            <Cpu className="w-3 h-3 text-blue-600" />
            <span>COLLECTION</span>
          </span>
          <span className="text-slate-800 font-medium truncate max-w-[110px]">anna_rag_documents</span>
        </div>
        <div className="flex items-center justify-between text-[10px]">
          <span className="text-slate-500">EMBEDDING</span>
          <span className="text-blue-700 font-medium">1024-dim dense</span>
        </div>
      </div>

      {/* Footer / System Status & Settings */}
      <div className="p-3 border-t border-slate-200 space-y-2 bg-white">
        {/* Health status pill */}
        <button
          onClick={onRefreshHealth}
          title="点击刷新后端服务状态"
          className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-slate-50 border border-slate-200 hover:border-slate-300 text-slate-700 text-xs font-mono transition-colors cursor-pointer"
        >
          <div className="flex items-center gap-2 min-w-0">
            <span
              className={`w-2 h-2 rounded-full shrink-0 ${
                isHealthy ? 'bg-emerald-500 shadow-xs' : 'bg-rose-500'
              }`}
            />
            <span className="truncate text-[11px] font-medium">
              {isHealthy ? 'API :8001 Connected' : 'API Offline'}
            </span>
          </div>
          <RefreshCw
            className={`w-3 h-3 text-slate-400 shrink-0 ${healthLoading ? 'animate-spin' : ''}`}
          />
        </button>

        {/* Settings button */}
        <button
          onClick={onOpenSettings}
          className="w-full flex items-center justify-center gap-2 px-2.5 py-1.5 rounded-lg text-slate-600 hover:text-slate-900 hover:bg-slate-100 text-[11px] font-medium transition-colors font-mono cursor-pointer"
        >
          <Settings className="w-3.5 h-3.5 text-slate-400" />
          <span>服务与 API 配置</span>
        </button>
      </div>
    </aside>
  );
};
