export type DocumentStatus = 'pending' | 'success' | 'failed';

export interface DocumentItem {
  id: string;
  name: string;
  status: DocumentStatus;
  chunk_count: number;
  created_at: string | null;
  indexed_at: string | null;
  error_message: string | null;
}

export interface DocumentListResponse {
  items: DocumentItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface UploadResponse {
  document_id: string;
  name: string;
  status: DocumentStatus;
}

export interface SearchHit {
  document_id?: string;
  document_name: string;
  chunk_index?: number;
  chunk_count?: number;
  score: number;
  text: string;
}

export interface SearchResponse {
  query: string;
  hits: SearchHit[];
}

export interface HealthResponse {
  status: string;
}

export type ActiveView = 'search' | 'documents' | 'evaluation';

export interface TargetChunkLink {
  documentId: string;
  chunkIndex?: number;
  documentName?: string;
  chunkText?: string;
}

export interface ToastMessage {
  id: string;
  type: 'success' | 'error' | 'info' | 'warning';
  title: string;
  description?: string;
}

export interface SelectedChunkInfo {
  document_id: string;
  document_name: string;
  chunk_index: number;
  text: string;
}

// ----------------------------------------------------
// Evaluation & TestSet Types
// ----------------------------------------------------

export type TestSetStatus = 'generating' | 'ready' | 'failed';
export type EvalItemStatus = 'pending' | 'ready' | 'failed';

export interface TestSetItem {
  id: string;
  answer_document_id: string;
  answer_chunk_index: number;
  query?: string | null;
  status: EvalItemStatus;
  error_message?: string | null;
  document_name?: string;
  context_text?: string;
}

export interface TestSet {
  id: string;
  name: string;
  status: TestSetStatus;
  progress_done: number;
  progress_total: number;
  error_message?: string | null;
  created_at: string;
  items?: TestSetItem[];
}

export interface CreateTestSetPayload {
  name?: string;
}

export interface AddItemsPayload {
  chunks: { document_id: string; chunk_index: number }[];
}

export interface ListTestSetsResponse {
  testsets: TestSet[];
}

// ----------------------------------------------------
// Eval Runs Types
// ----------------------------------------------------

export type EvalRunStatus = 'running' | 'done' | 'failed';

export interface EvalRunConfig {
  top_k: number;
  query_rewrite: boolean;
}

export interface EvalRunMetrics {
  [key: string]: number | undefined;
  mrr?: number;
  avg_latency_ms?: number;
  queries?: number;
}

export interface EvalRunItem {
  testset_item_id: string;
  query: string;
  answer_document_id: string;
  answer_chunk_index: number;
  hit_rank: number | null;
  recall: number;
  mrr: number;
  low_recall: boolean;
  latency_ms: number;
}

export interface EvalRun {
  id: string;
  testset_id: string;
  status: EvalRunStatus;
  config: EvalRunConfig;
  metrics: EvalRunMetrics | null;
  error_message?: string | null;
  progress_done: number;
  progress_total: number;
  created_at: string;
  finished_at?: string | null;
  items?: EvalRunItem[];
}

