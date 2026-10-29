import React, { useState } from 'react';
import { Layers, Lock, User, Loader2, AlertCircle } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { formatErrorMessage } from '../../api/client';
import { useToast } from '../../context/ToastContext';

interface LoginPageProps {
  onNavigateToRegister: () => void;
  onLoginSuccess: () => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({
  onNavigateToRegister,
  onLoginSuccess,
}) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { login } = useAuth();
  const { addToast } = useToast();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError('请输入用户名或邮箱以及密码');
      return;
    }

    setLoading(true);
    setError(null);
    try {
      await login({
        username: username.trim(),
        password,
      });
      addToast('success', '登录成功', '欢迎回来！');
      onLoginSuccess();
    } catch (err) {
      const msg = formatErrorMessage(err);
      setError(msg);
      addToast('error', '登录失败', msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen w-screen flex items-center justify-center bg-slate-100 p-4 font-sans select-none">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-xl border border-slate-200 overflow-hidden">
        {/* Brand Header */}
        <div className="p-8 pb-6 text-center border-b border-slate-100 bg-slate-50/50">
          <div className="w-12 h-12 rounded-xl bg-blue-600 flex items-center justify-center text-white mx-auto shadow-md mb-3">
            <Layers className="w-6 h-6" />
          </div>
          <h1 className="text-xl font-bold text-slate-900 tracking-tight font-mono">
            RecallDesk Studio
          </h1>
        </div>

        {/* Form Body */}
        <div className="p-8 pt-6">
          <h2 className="text-base font-semibold text-slate-800 mb-4">账号登录</h2>

          {error && (
            <div className="mb-4 p-3 bg-rose-50 border border-rose-200 rounded-xl flex items-start gap-2.5 text-xs text-rose-700">
              <AlertCircle className="w-4 h-4 text-rose-500 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4 text-xs font-mono">
            <div>
              <label className="block text-slate-700 font-medium mb-1.5 text-xs">
                用户名或邮箱
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                  <User className="w-4 h-4" />
                </div>
                <input
                  type="text"
                  required
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="请输入用户名或注册邮箱"
                  className="w-full pl-9 pr-3.5 py-2.5 bg-slate-50 border border-slate-300 rounded-xl text-slate-900 placeholder-slate-400 text-sm focus:outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100 transition-all font-mono"
                  autoComplete="username"
                />
              </div>
            </div>

            <div>
              <label className="block text-slate-700 font-medium mb-1.5 text-xs">
                密码
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                  <Lock className="w-4 h-4" />
                </div>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="请输入密码"
                  className="w-full pl-9 pr-3.5 py-2.5 bg-slate-50 border border-slate-300 rounded-xl text-slate-900 placeholder-slate-400 text-sm focus:outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100 transition-all font-mono"
                  autoComplete="current-password"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 disabled:opacity-60 text-white font-semibold rounded-xl text-sm shadow-xs transition-all cursor-pointer"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>正在登录...</span>
                </>
              ) : (
                <span>登录</span>
              )}
            </button>
          </form>

          {/* Footer switch */}
          <div className="mt-6 pt-5 border-t border-slate-100 text-center text-xs text-slate-500 font-mono">
            <span>还没有账号？</span>
            <button
              type="button"
              onClick={onNavigateToRegister}
              className="ml-1.5 text-blue-600 hover:text-blue-700 font-semibold hover:underline cursor-pointer"
            >
              立即注册
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
