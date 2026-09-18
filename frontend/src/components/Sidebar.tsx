import React from 'react';
import { ActiveView, HealthResponse } from '../types';
import {
  Search,
  Database,
  Plus,
  Settings,
  Layers,
  BarChart2,
  Share2,
} from 'lucide-react';

interface SidebarProps {
  activeView: ActiveView;
  setActiveView: (view: ActiveView) => void;
  health?: HealthResponse | null;
  healthLoading?: boolean;
  onRefreshHealth?: () => void;
  onOpenSettings: () => void;
  onOpenUpload: () => void;
  documentCount: number;
  evalQuestionCount?: number;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeView,
  setActiveView,
  onOpenSettings,
  onOpenUpload,
  documentCount,
  evalQuestionCount = 0,
}) => {
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
            <p className="text-[11px] text-slate-500 font-mono">Hybrid &amp; Graph RAG Hub</p>
          </div>
        </div>

        <button
          onClick={onOpenSettings}
          className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
          title="服务与 API 配置"
        >
          <Settings className="w-4 h-4" />
        </button>
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

        {/* Knowledge Graph Explorer item */}
        <button
          onClick={() => setActiveView('graph')}
          className={`w-full flex items-center justify-between px-3 py-2 rounded-lg font-medium transition-colors cursor-pointer ${
            activeView === 'graph'
              ? 'bg-blue-50 text-blue-700 font-semibold border border-blue-200 shadow-xs'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
          }`}
        >
          <div className="flex items-center gap-2.5">
            <Share2 className={`w-4 h-4 ${activeView === 'graph' ? 'text-blue-600' : 'text-slate-400'}`} />
            <span>知识图谱 (Graph)</span>
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
    </aside>
  );
};
