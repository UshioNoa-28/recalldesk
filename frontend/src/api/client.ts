import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import {
  DocumentItem,
  DocumentListResponse,
  HealthResponse,
  SearchResponse,
  UploadResponse,
  TestSet,
  CreateTestSetPayload,
  EvalRun,
  CreateRunPayload,
  User,
  TokenPair,
  LoginPayload,
  RegisterPayload,
} from '../types';

const STORAGE_KEY_API_BASE = 'recalldesk_api_base_url';
export const STORAGE_KEY_ACCESS_TOKEN = 'recalldesk_access_token';
export const STORAGE_KEY_REFRESH_TOKEN = 'recalldesk_refresh_token';

export const getApiBaseUrl = (): string => {
  return localStorage.getItem(STORAGE_KEY_API_BASE) || '/api';
};

export const setApiBaseUrl = (url: string): void => {
  if (!url) {
    localStorage.removeItem(STORAGE_KEY_API_BASE);
  } else {
    localStorage.setItem(STORAGE_KEY_API_BASE, url.replace(/\/+$/, ''));
  }
};

export const getAccessToken = (): string | null => {
  return localStorage.getItem(STORAGE_KEY_ACCESS_TOKEN);
};

export const getRefreshToken = (): string | null => {
  return localStorage.getItem(STORAGE_KEY_REFRESH_TOKEN);
};

export const setTokens = (accessToken: string, refreshToken: string): void => {
  localStorage.setItem(STORAGE_KEY_ACCESS_TOKEN, accessToken);
  localStorage.setItem(STORAGE_KEY_REFRESH_TOKEN, refreshToken);
};

export const clearTokens = (): void => {
  localStorage.removeItem(STORAGE_KEY_ACCESS_TOKEN);
  localStorage.removeItem(STORAGE_KEY_REFRESH_TOKEN);
};

const redirectToLogin = (): void => {
  if (
    typeof window !== 'undefined' &&
    window.location.hash !== '#/login' &&
    window.location.hash !== '#/register'
  ) {
    window.location.hash = '#/login';
  }
};

export const apiClient = axios.create({
  timeout: 30000,
});

apiClient.interceptors.request.use((config) => {
  config.baseURL = getApiBaseUrl();
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

interface CustomRequestConfig extends InternalAxiosRequestConfig {
  _retry?: boolean;
}

let refreshPromise: Promise<string> | null = null;

apiClient.interceptors.response.use(
  (response) => response,
  async (error: unknown) => {
    if (!axios.isAxiosError(error) || !error.config) {
      return Promise.reject(error);
    }

    const originalRequest = error.config as CustomRequestConfig;
    const status = error.response?.status;
    const url = originalRequest.url || '';

    // If 401 occurs on public auth endpoints, do not attempt token refresh
    const isAuthRoute =
      url.includes('/auth/login') ||
      url.includes('/auth/register') ||
      url.includes('/auth/email-code') ||
      url.includes('/auth/refresh');

    if (status === 401 && !isAuthRoute && !originalRequest._retry) {
      originalRequest._retry = true;
      const refreshToken = getRefreshToken();

      if (!refreshToken) {
        clearTokens();
        redirectToLogin();
        return Promise.reject(error);
      }

      if (!refreshPromise) {
        refreshPromise = (async () => {
          try {
            const res = await axios.post<TokenPair>(
              `${getApiBaseUrl()}/auth/refresh`,
              { refresh_token: refreshToken },
              { timeout: 15000 }
            );
            const { access_token, refresh_token: newRefreshToken } = res.data;
            setTokens(access_token, newRefreshToken || refreshToken);
            return access_token;
          } catch (refreshErr) {
            clearTokens();
            redirectToLogin();
            throw refreshErr;
          } finally {
            refreshPromise = null;
          }
        })();
      }

      try {
        const newAccessToken = await refreshPromise;
        originalRequest.headers.Authorization = `Bearer ${newAccessToken}`;
        return apiClient(originalRequest);
      } catch (refreshErr) {
        return Promise.reject(refreshErr);
      }
    }

    return Promise.reject(error);
  }
);

interface ErrorDetailObject {
  reason?: string;
  message?: string;
  msg?: string;
  [key: string]: unknown;
}

export const formatErrorMessage = (error: unknown): string => {
  if (axios.isAxiosError(error)) {
    const err = error as AxiosError<{
      detail?: string | ErrorDetailObject | Array<ErrorDetailObject | string>;
    }>;

    if (err.response?.status === 403) {
      const detail = err.response.data?.detail;
      if (typeof detail === 'string') return detail;
      return '文档配额已超限，无法继续上传';
    }

    if (err.response?.status === 429) {
      const retryAfter = err.response.headers['retry-after'];
      const detail = err.response.data?.detail;
      if (typeof detail === 'string') return detail;
      if (retryAfter) {
        return `请求过于频繁，请在 ${retryAfter} 秒后重试`;
      }
      return '请求过于频繁，请稍后再试';
    }

    if (err.response?.data?.detail) {
      const detail = err.response.data.detail;
      if (typeof detail === 'string') {
        return detail;
      }
      if (Array.isArray(detail)) {
        return detail
          .map((d) => {
            if (typeof d === 'string') return d;
            return d.msg || d.message || JSON.stringify(d);
          })
          .join(', ');
      }
      if (typeof detail === 'object' && detail !== null) {
        if (detail.message) {
          return String(detail.message);
        }
        if (detail.reason === 'username_taken') {
          return '用户名已被占用，请更换其他用户名';
        }
        return JSON.stringify(detail);
      }
    }

    if (err.response?.status === 401) {
      return '登录已过期或凭证无效，请重新登录';
    }
    if (err.response?.status === 413) {
      return '文件体积过大';
    }
    if (err.response?.status === 404) {
      return '请求的资源未找到 (404)';
    }
    if (err.response?.status === 405) {
      return '请求方法不被允许 (405)';
    }
    if (err.message === 'Network Error') {
      return '无法连接到后端服务，请确认后端已启动（或检查跨域 / 代理配置）';
    }
    return err.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return '发生未知错误';
};

export interface ChunkItem {
  document_id: string;
  document_name: string;
  chunk_index: number;
  chunk_count?: number;
  text: string;
}

export const api = {
  // ----------------------------------------------------
  // Auth API
  // ----------------------------------------------------

  async sendEmailCode(email: string): Promise<{ detail: string }> {
    const response = await apiClient.post<{ detail: string }>('/auth/email-code', { email });
    return response.data;
  },

  async register(payload: RegisterPayload): Promise<TokenPair> {
    const response = await apiClient.post<TokenPair>('/auth/register', payload);
    return response.data;
  },

  async login(payload: LoginPayload): Promise<TokenPair> {
    const response = await apiClient.post<TokenPair>('/auth/login', payload);
    return response.data;
  },

  async refresh(refreshToken: string): Promise<TokenPair> {
    const response = await apiClient.post<TokenPair>('/auth/refresh', {
      refresh_token: refreshToken,
    });
    return response.data;
  },

  async getMe(): Promise<User> {
    const response = await apiClient.get<User>('/auth/me');
    return response.data;
  },

  async logout(): Promise<void> {
    await apiClient.post('/auth/logout');
  },

  // ----------------------------------------------------
  // Document & System API
  // ----------------------------------------------------

  async getHealth(): Promise<HealthResponse> {
    const response = await apiClient.get<HealthResponse>('/health');
    return response.data;
  },

  async uploadDocument(file: File): Promise<UploadResponse> {
    const formData = new FormData();
    formData.append('file', file);
    const response = await apiClient.post<UploadResponse>('/documents', formData);
    return response.data;
  },

  async listDocuments(page = 1, pageSize = 20): Promise<DocumentListResponse> {
    const response = await apiClient.get<DocumentListResponse>('/documents', {
      params: {
        page,
        page_size: pageSize,
      },
    });
    return response.data;
  },

  async getDocument(documentId: string): Promise<DocumentItem> {
    const response = await apiClient.get<DocumentItem>(`/documents/${documentId}`);
    return response.data;
  },

  async deleteDocument(documentId: string): Promise<{ document_id: string; deleted: boolean }> {
    const response = await apiClient.delete<{ document_id: string; deleted: boolean }>(
      `/documents/${documentId}`
    );
    return response.data;
  },

  async reindexDocument(documentId: string): Promise<UploadResponse> {
    const response = await apiClient.post<UploadResponse>(`/documents/${documentId}/reindex`);
    return response.data;
  },

  async getDocumentChunks(
    documentId: string
  ): Promise<{ document_id: string; total_chunks: number; chunks: ChunkItem[] }> {
    const response = await apiClient.get<{
      document_id: string;
      total_chunks: number;
      chunks: ChunkItem[];
    }>(`/documents/${documentId}/chunks`);
    return response.data;
  },

  async getDocumentContent(documentId: string): Promise<string> {
    const response = await apiClient.get<string>(`/documents/${documentId}/content`, {
      responseType: 'text',
    });
    return response.data;
  },

  async downloadDocument(documentId: string, filename = 'document.txt'): Promise<void> {
    const response = await apiClient.get<Blob>(`/documents/${documentId}/content`, {
      params: { download: 'true' },
      responseType: 'blob',
    });
    const blobUrl = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = blobUrl;
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(blobUrl);
  },

  getDownloadUrl(documentId: string): string {
    const base = getApiBaseUrl();
    return `${base}/documents/${documentId}/content?download=true`;
  },

  async search(query: string, topK = 5): Promise<SearchResponse> {
    const response = await apiClient.get<SearchResponse>('/search', {
      params: {
        q: query,
        top_k: topK,
      },
    });
    return response.data;
  },

  // ----------------------------------------------------
  // Evaluation TestSets API
  // ----------------------------------------------------

  async createTestSet(name?: string): Promise<TestSet> {
    const payload: CreateTestSetPayload = { name: name?.trim() || undefined };
    const response = await apiClient.post<TestSet>('/eval/testsets', payload);
    return response.data;
  },

  /**
   * POST /eval/testsets/{testset_id}/items
   * 上传 .jsonl 格式题目文件，multipart/form-data，字段名为 file
   */
  async uploadTestSetItems(testsetId: string, file: File): Promise<TestSet> {
    const formData = new FormData();
    formData.append('file', file);
    const response = await apiClient.post<TestSet>(
      `/eval/testsets/${testsetId}/items`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    );
    return response.data;
  },

  async listTestSets(): Promise<TestSet[]> {
    const response = await apiClient.get<{ testsets: TestSet[] } | TestSet[]>('/eval/testsets');
    if ('testsets' in response.data && Array.isArray(response.data.testsets)) {
      return response.data.testsets;
    }
    if (Array.isArray(response.data)) {
      return response.data;
    }
    return [];
  },

  async getTestSet(testsetId: string): Promise<TestSet> {
    const response = await apiClient.get<TestSet>(`/eval/testsets/${testsetId}`);
    return response.data;
  },

  async deleteTestSet(testsetId: string): Promise<{ testset_id: string; deleted: boolean }> {
    const response = await apiClient.delete<{ testset_id: string; deleted: boolean }>(
      `/eval/testsets/${testsetId}`
    );
    return response.data;
  },

  async createRun(
    testsetId: string,
    payload?: number | CreateRunPayload
  ): Promise<EvalRun> {
    let body: CreateRunPayload = {};
    if (typeof payload === 'number') {
      body = { top_k: payload };
    } else if (payload) {
      body = payload;
    }
    const response = await apiClient.post<EvalRun>(
      `/eval/testsets/${testsetId}/runs`,
      body
    );
    return response.data;
  },

  async listRuns(testsetId: string): Promise<EvalRun[]> {
    const response = await apiClient.get<{ runs: EvalRun[] }>(`/eval/testsets/${testsetId}/runs`);
    return response.data?.runs || [];
  },

  async rerunEvalRun(runId: string): Promise<EvalRun> {
    const response = await apiClient.post<EvalRun>(`/eval/runs/${runId}/rerun_failed`);
    return response.data;
  },

  async getRun(runId: string): Promise<EvalRun> {
    const response = await apiClient.get<EvalRun>(`/eval/runs/${runId}`);
    return response.data;
  },
};
