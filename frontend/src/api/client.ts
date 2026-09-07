import axios, { AxiosError } from 'axios';
import {
  DocumentItem,
  DocumentListResponse,
  HealthResponse,
  SearchResponse,
  UploadResponse,
  TestSet,
  CreateTestSetPayload,
  AddItemsPayload,
  EvalRun,
} from '../types';

const STORAGE_KEY_API_BASE = 'recalldesk_api_base_url';

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

export const apiClient = axios.create({
  timeout: 30000,
});

apiClient.interceptors.request.use((config) => {
  config.baseURL = getApiBaseUrl();
  return config;
});

export const formatErrorMessage = (error: unknown): string => {
  if (axios.isAxiosError(error)) {
    const err = error as AxiosError<{ detail?: string | { msg?: string }[] }>;
    if (err.response?.data?.detail) {
      if (typeof err.response.data.detail === 'string') {
        return err.response.data.detail;
      }
      if (Array.isArray(err.response.data.detail)) {
        return err.response.data.detail.map((d) => d.msg || JSON.stringify(d)).join(', ');
      }
      return JSON.stringify(err.response.data.detail);
    }
    if (err.response?.status === 413) {
      return '文件体积过大（单文件上限 10MB）';
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
  chunk_index: number;
  chunk_count?: number;
  text: string;
  point_id?: string;
  score?: number;
}

export const api = {
  async getHealth(): Promise<HealthResponse> {
    const response = await apiClient.get<HealthResponse>('/health');
    return response.data;
  },

  async uploadDocument(file: File): Promise<UploadResponse> {
    const formData = new FormData();
    formData.append('file', file);
    const response = await apiClient.post<UploadResponse>('/documents', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
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

  /**
   * POST /eval/testsets
   * 创建一个空评测集
   */
  async createTestSet(name?: string): Promise<TestSet> {
    const payload: CreateTestSetPayload = { name: name?.trim() || undefined };
    const response = await apiClient.post<TestSet>('/eval/testsets', payload);
    return response.data;
  },

  /**
   * POST /eval/testsets/{testset_id}/items
   * 往指定评测集添加切片出题任务
   */
  async addItemsToTestSet(
    testsetId: string,
    chunks: { document_id: string; chunk_index: number }[]
  ): Promise<TestSet> {
    const payload: AddItemsPayload = { chunks };
    const response = await apiClient.post<TestSet>(`/eval/testsets/${testsetId}/items`, payload);
    return response.data;
  },

  /**
   * 组合辅助函数：新建评测集并立刻添加选中的切片
   */
  async createTestSetWithChunks(
    name: string | undefined,
    chunks: { document_id: string; chunk_index: number }[]
  ): Promise<TestSet> {
    const testset = await this.createTestSet(name);
    if (chunks.length > 0) {
      return await this.addItemsToTestSet(testset.id, chunks);
    }
    return testset;
  },

  /**
   * GET /eval/testsets
   * 列出所有评测集
   */
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

  /**
   * GET /eval/testsets/{testset_id}
   * 获取评测集详情（含所有 items）
   */
  async getTestSet(testsetId: string): Promise<TestSet> {
    const response = await apiClient.get<TestSet>(`/eval/testsets/${testsetId}`);
    return response.data;
  },

  /**
   * DELETE /eval/testsets/{testset_id}
   * 删除评测集
   */
  async deleteTestSet(testsetId: string): Promise<{ testset_id: string; deleted: boolean }> {
    const response = await apiClient.delete<{ testset_id: string; deleted: boolean }>(
      `/eval/testsets/${testsetId}`
    );
    return response.data;
  },

  /**
   * POST /eval/testsets/{testset_id}/runs
   * 发起一次检索评测运行
   */
  async createRun(testsetId: string, topK?: number): Promise<EvalRun> {
    const payload = topK ? { top_k: topK } : {};
    const response = await apiClient.post<EvalRun>(`/eval/testsets/${testsetId}/runs`, payload);
    return response.data;
  },

  /**
   * GET /eval/testsets/{testset_id}/runs
   * 列出某评测集的所有历史评测运行
   */
  async listRuns(testsetId: string): Promise<EvalRun[]> {
    const response = await apiClient.get<{ runs: EvalRun[] }>(`/eval/testsets/${testsetId}/runs`);
    return response.data?.runs || [];
  },

  /**
   * GET /eval/runs/{run_id}
   * 获取某次评测运行的详情（包含指标及每道题的打分详情）
   */
  async getRun(runId: string): Promise<EvalRun> {
    const response = await apiClient.get<EvalRun>(`/eval/runs/${runId}`);
    return response.data;
  },
};
