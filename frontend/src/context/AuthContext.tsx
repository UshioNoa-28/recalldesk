import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { User, LoginPayload, RegisterPayload } from '../types';
import { api, getAccessToken, setTokens, clearTokens } from '../api/client';

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  sendEmailCode: (email: string) => Promise<string>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const refreshUser = useCallback(async () => {
    const token = getAccessToken();
    if (!token) {
      setUser(null);
      setIsLoading(false);
      return;
    }
    try {
      const profile = await api.getMe();
      setUser(profile);
    } catch {
      clearTokens();
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  const login = async (payload: LoginPayload): Promise<void> => {
    const res = await api.login(payload);
    setTokens(res.access_token, res.refresh_token);
    setUser(res.user);
  };

  const register = async (payload: RegisterPayload): Promise<void> => {
    const res = await api.register(payload);
    setTokens(res.access_token, res.refresh_token);
    setUser(res.user);
  };

  const sendEmailCode = async (email: string): Promise<string> => {
    const res = await api.sendEmailCode(email);
    return res.detail || '验证码已发送';
  };

  const logout = (): void => {
    // 先让服务端作废这对令牌（把该用户的吊销时间点推到此刻），失败也照样清本地：
    // 网络不通时用户点登出，至少不能让界面还停在已登录状态
    void api.logout().catch(() => undefined).finally(() => {
      clearTokens();
      setUser(null);
      window.location.hash = '#/login';
    });
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: Boolean(user),
        isLoading,
        login,
        register,
        sendEmailCode,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
