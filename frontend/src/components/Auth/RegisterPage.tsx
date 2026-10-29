import React, { useState, useEffect, useRef } from 'react';
import { Layers, Lock, User, Mail, ShieldCheck, Loader2, AlertCircle, CheckCircle2 } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { formatErrorMessage } from '../../api/client';
import { useToast } from '../../context/ToastContext';

interface RegisterPageProps {
  onNavigateToLogin: () => void;
  onRegisterSuccess: () => void;
}

export const RegisterPage: React.FC<RegisterPageProps> = ({
  onNavigateToLogin,
  onRegisterSuccess,
}) => {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');

  const [sendingCode, setSendingCode] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [codeSentSuccess, setCodeSentSuccess] = useState<string | null>(null);

  const [registering, setRegistering] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { register, sendEmailCode } = useAuth();
  const { addToast } = useToast();
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (countdown > 0) {
      timerRef.current = window.setTimeout(() => {
        setCountdown((prev) => prev - 1);
      }, 1000);
    }
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, [countdown]);

  const handleSendCode = async () => {
    setError(null);
    const cleanEmail = email.trim();
    if (!cleanEmail) {
      setError('请先输入邮箱地址');
      return;
    }
    // Basic email format check
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) {
      setError('请输入有效的邮箱地址');
      return;
    }

    setSendingCode(true);
    try {
      await sendEmailCode(cleanEmail);
      setCountdown(60);
      setCodeSentSuccess(`验证码已发送至 ${cleanEmail}`);
      addToast('success', '验证码已发送', `已发送至 ${cleanEmail}`);
    } catch (err) {
      const msg = formatErrorMessage(err);
      setError(msg);
      addToast('error', '验证码发送失败', msg);
    } finally {
      setSendingCode(false);
    }
  };

  const handleCodeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    // 6-digit digits only constraint, paste-friendly
    const val = e.target.value.replace(/\D/g, '').slice(0, 6);
    setCode(val);
  };

  const handlePasteCode = (e: React.ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData('text');
    const val = pasted.replace(/\D/g, '').slice(0, 6);
    setCode(val);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const cleanUsername = username.trim();
    const cleanEmail = email.trim();

    if (!cleanUsername) {
      setError('请填写用户名');
      return;
    }
    if (!cleanEmail) {
      setError('请填写邮箱');
      return;
    }
    if (!password) {
      setError('请填写密码');
      return;
    }
    if (code.length !== 6) {
      setError('请输入收到的 6 位数字验证码');
      return;
    }

    setRegistering(true);
    try {
      await register({
        username: cleanUsername,
        password,
        email: cleanEmail,
        code,
      });
      addToast('success', '注册成功', '已自动登录系统');
      onRegisterSuccess();
    } catch (err) {
      const msg = formatErrorMessage(err);
      setError(msg);
      addToast('error', '注册失败', msg);
    } finally {
      setRegistering(false);
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
          <h2 className="text-base font-semibold text-slate-800 mb-4">账号注册</h2>

          {error && (
            <div className="mb-4 p-3 bg-rose-50 border border-rose-200 rounded-xl flex items-start gap-2.5 text-xs text-rose-700">
              <AlertCircle className="w-4 h-4 text-rose-500 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {codeSentSuccess && (
            <div className="mb-4 p-3 bg-emerald-50 border border-emerald-200 rounded-xl flex items-start gap-2.5 text-xs text-emerald-800 font-mono">
              <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
              <span>{codeSentSuccess}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4 text-xs font-mono">
            {/* 用户名 */}
            <div>
              <label className="block text-slate-700 font-medium mb-1.5 text-xs">
                用户名
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
                  placeholder="请输入用户名"
                  className="w-full pl-9 pr-3.5 py-2.5 bg-slate-50 border border-slate-300 rounded-xl text-slate-900 placeholder-slate-400 text-sm focus:outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100 transition-all font-mono"
                  autoComplete="username"
                />
              </div>
            </div>

            {/* 邮箱 */}
            <div>
              <label className="block text-slate-700 font-medium mb-1.5 text-xs">
                邮箱
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                  <Mail className="w-4 h-4" />
                </div>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="请输入邮箱地址"
                  className="w-full pl-9 pr-3.5 py-2.5 bg-slate-50 border border-slate-300 rounded-xl text-slate-900 placeholder-slate-400 text-sm focus:outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100 transition-all font-mono"
                  autoComplete="email"
                />
              </div>
            </div>

            {/* 验证码 + 发送按钮 */}
            <div>
              <label className="block text-slate-700 font-medium mb-1.5 text-xs">
                验证码
              </label>
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                    <ShieldCheck className="w-4 h-4" />
                  </div>
                  <input
                    type="text"
                    maxLength={6}
                    required
                    value={code}
                    onChange={handleCodeChange}
                    onPaste={handlePasteCode}
                    placeholder="请输入 6 位验证码"
                    className="w-full pl-9 pr-3.5 py-2.5 bg-slate-50 border border-slate-300 rounded-xl text-slate-900 placeholder-slate-400 text-sm focus:outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100 transition-all font-mono"
                  />
                </div>
                <button
                  type="button"
                  onClick={handleSendCode}
                  disabled={sendingCode || countdown > 0}
                  className="shrink-0 px-4 py-2.5 bg-slate-100 hover:bg-slate-200 active:bg-slate-300 border border-slate-300 text-slate-700 font-medium rounded-xl text-xs disabled:opacity-50 disabled:cursor-not-allowed transition-all cursor-pointer whitespace-nowrap"
                >
                  {sendingCode ? (
                    <span className="flex items-center gap-1.5">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      发送中
                    </span>
                  ) : countdown > 0 ? (
                    <span>{countdown}s 后重发</span>
                  ) : (
                    <span>发送验证码</span>
                  )}
                </button>
              </div>
            </div>

            {/* 密码 */}
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
                  placeholder="请输入登录密码"
                  className="w-full pl-9 pr-3.5 py-2.5 bg-slate-50 border border-slate-300 rounded-xl text-slate-900 placeholder-slate-400 text-sm focus:outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100 transition-all font-mono"
                  autoComplete="new-password"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={registering}
              className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 disabled:opacity-60 text-white font-semibold rounded-xl text-sm shadow-xs transition-all cursor-pointer"
            >
              {registering ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>正在注册...</span>
                </>
              ) : (
                <span>立即注册</span>
              )}
            </button>
          </form>

          {/* Footer switch */}
          <div className="mt-6 pt-5 border-t border-slate-100 text-center text-xs text-slate-500 font-mono">
            <span>已有账号？</span>
            <button
              type="button"
              onClick={onNavigateToLogin}
              className="ml-1.5 text-blue-600 hover:text-blue-700 font-semibold hover:underline cursor-pointer"
            >
              直接登录
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
