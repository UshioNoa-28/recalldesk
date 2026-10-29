import React from 'react';
import { ActiveView, HealthResponse } from '../../types';
import { useAuth } from '../../context/AuthContext';
import {
  Mail,
  LogOut,
  Settings,
  Search,
  Database,
  BarChart2,
} from 'lucide-react';

interface TopBarProps {
  activeView: ActiveView;
  health?: HealthResponse | null;
  healthLoading?: boolean;
  onRefreshHealth?: () => void;
  onOpenSettings: () => void;
}

const VIEW_TITLES: Record<string, { label: string; desc: string; icon: React.ElementType }> = {
  search: {
    label: '向量检索 (Search)',
    desc: 'Dense + Sparse 混合检索与重排序控制台',
    icon: Search,
  },
  documents: {
    label: '文档与切片 (Chunks)',
    desc: '知识库文档管理、自动切片查看与引文复制',
    icon: Database,
  },
  evaluation: {
    label: '切片评测中心 (Eval Studio)',
    desc: 'JSONL 题目同步解析导入与端到端检索指标评测',
    icon: BarChart2,
  },
};

export const TopBar: React.FC<TopBarProps> = ({
  activeView,
  onOpenSettings,
}) => {
  const { user, logout } = useAuth();
  const currentView = VIEW_TITLES[activeView] || {
    label: 'RecallDesk Studio',
    desc: '混合检索与评测平台',
    icon: Search,
  };
  const IconComponent = currentView.icon;

  return (
    <header className="h-14 border-b border-slate-200 bg-white px-5 flex items-center justify-between shrink-0 select-none">
      {/* Left: View breadcrumb */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-700">
          <IconComponent className="w-4 h-4" />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-slate-900 tracking-tight">
            {currentView.label}
          </h2>
          <p className="text-xs text-slate-500">{currentView.desc}</p>
        </div>
      </div>

      {/* Right: User Info + Logout + Settings */}
      <div className="flex items-center gap-3">
        {/* User Info */}
        {user && (
          <div className="flex items-center gap-2.5 pl-3 border-l border-slate-200">
            <div className="w-7 h-7 rounded-full bg-slate-200 border border-slate-300 text-slate-700 flex items-center justify-center font-semibold text-xs">
              {user.username.charAt(0).toUpperCase()}
            </div>
            <div className="text-left font-mono">
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-semibold text-slate-800 leading-tight">
                  {user.username}
                </span>
              </div>
              <div className="flex items-center gap-1 text-xs text-slate-500 leading-tight">
                {user.email ? (
                  <>
                    <Mail className="w-3.5 h-3.5 text-slate-400" />
                    <span>{user.email}</span>
                  </>
                ) : (
                  <span className="text-slate-400">未绑定邮箱</span>
                )}
              </div>
            </div>

            {/* Logout button */}
            <button
              onClick={logout}
              className="ml-1 p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors cursor-pointer"
              title="退出登录"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Settings button */}
        <button
          onClick={onOpenSettings}
          className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
          title="系统与代理配置"
        >
          <Settings className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
};
