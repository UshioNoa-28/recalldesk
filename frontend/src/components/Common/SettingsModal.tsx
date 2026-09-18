import React, { useState } from 'react';
import { X, Server, Check, RotateCcw, AlertTriangle } from 'lucide-react';
import { getApiBaseUrl, setApiBaseUrl } from '../../api/client';
import { useToast } from '../../context/ToastContext';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose, onSaved }) => {
  const [url, setUrl] = useState(getApiBaseUrl());
  const { addToast } = useToast();

  if (!isOpen) return null;

  const handleSave = () => {
    setApiBaseUrl(url.trim());
    addToast('success', '配置已更新', `后端地址已设为: ${url.trim() || '/api (Vite Proxy)'}`);
    onSaved();
    onClose();
  };

  const handleReset = () => {
    setUrl('/api');
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
      <div className="bg-white border border-slate-200 rounded-2xl max-w-md w-full p-6 shadow-xl space-y-5">
        <div className="flex items-center justify-between border-b border-slate-100 pb-4">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-blue-50 border border-blue-200 flex items-center justify-center text-blue-600">
              <Server className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-900">后端服务连接配置</h3>
              <p className="text-xs text-slate-500">设置前端请求的后端 API 地址</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 p-1 rounded-lg hover:bg-slate-100 transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="space-y-4 text-sm">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-2 font-mono">
              API BASE URL
            </label>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="/api 或 http://127.0.0.1:8001"
              className="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-300 rounded-xl text-slate-900 placeholder-slate-400 text-sm focus:outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100 font-mono"
            />
          </div>

          <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 space-y-2 text-xs text-slate-600 font-mono">
            <div className="flex items-center gap-2 text-slate-800 font-medium">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0" />
              <span>常用配置说明：</span>
            </div>
            <p>
              • <code className="text-blue-700 font-mono bg-blue-50 px-1 py-0.5 rounded border border-blue-200">/api</code>：使用 Vite / Nginx 代理转发至 8001 端口（免 CORS）。
            </p>
            <p>
              • <code className="text-blue-700 font-mono bg-blue-50 px-1 py-0.5 rounded border border-blue-200">http://127.0.0.1:8001</code>：直接向 FastAPI 发起请求。
            </p>
          </div>
        </div>

        <div className="flex items-center justify-between pt-3 border-t border-slate-100">
          <button
            onClick={handleReset}
            type="button"
            className="flex items-center gap-1.5 px-3 py-2 text-xs text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer font-mono"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            恢复默认 (/api)
          </button>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              type="button"
              className="px-4 py-2 text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
            >
              取消
            </button>
            <button
              onClick={handleSave}
              type="button"
              className="flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-all shadow-xs cursor-pointer"
            >
              <Check className="w-3.5 h-3.5" />
              保存配置
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
