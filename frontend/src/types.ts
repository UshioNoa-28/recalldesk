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

export type ActiveView = 'search' | 'documents' | 'evaluation' | 'login' | 'register';

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
// Auth Types
// ----------------------------------------------------

export interface User {
  id: string;
  username: string;
  email: string | null;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

export interface LoginPayload {
  username: string;
  password: string;
}

export interface RegisterPayload {
  username: string;
  password: string;
  email: string;
  code: string;
}

export interface EmailCodePayload {
  email: string;
}

export interface RefreshPayload {
  refresh_token: string;
}

// ----------------------------------------------------
// Evaluation & TestSet Types
// ----------------------------------------------------

export interface EvidenceItem {
  document_id: string;
  chunk_index: number;
}

export interface TestSetItem {
  id: string;
  query: string;
  evidence: EvidenceItem[];
}

export interface TestSet {
  id: string;
  name: string;
  item_count: number;
  created_at: string;
  items?: TestSetItem[];
}

export interface CreateTestSetPayload {
  name?: string;
}

export interface ListTestSetsResponse {
  testsets: TestSet[];
}

// ----------------------------------------------------
// Eval Runs Types
// ----------------------------------------------------

export type EvalRunStatus = 'running' | 'done' | 'failed';

export type FusionMethod = 'rrf' | 'weighted';
export type FusionNorm = 'minmax' | 'zscore';

export interface FusionConfig {
  method: FusionMethod;
  rrf_k: number;
  norm: FusionNorm;
  weights: {
    dense: number;
    sparse: number;
    [key: string]: number;
  };
}

export interface EvalRunConfig {
  top_k: number;
  query_rewrite: boolean;
  rerank: boolean;
  fusion?: FusionConfig;
}

export interface CreateRunPayload {
  top_k?: number;
  query_rewrite?: boolean;
  rerank?: boolean;
  fusion?: {
    method?: FusionMethod;
    rrf_k?: number;
    norm?: FusionNorm;
    weights?: Record<string, number>;
  };
}

export interface EvalRunBucketSummary {
  [key: string]: number | undefined;
  evidence_coverage?: number;
  queries?: number;
}

export type ChannelKind = 'dense_original' | 'dense_variant' | 'sparse' | 'union' | string;

export interface EvalChannelSummary {
  [key: string]: number | undefined;
  evidence_coverage?: number;
  queries?: number;
}

export interface EvalRunMetrics {
  [key: string]: unknown;
  avg_latency_ms?: number;
  evidence_coverage?: number;
  queries?: number;
  buckets?: {
    single_hop: EvalRunBucketSummary;
    multi_hop: EvalRunBucketSummary;
  };
  channels?: Record<string, EvalChannelSummary>;
}

export interface EvalChannelScore {
  kind: ChannelKind;
  text: string | null;
  ranks: number[];
  recall: number; // 0 or 1
  map: number | null;
  evidence_matched: number;
}

export interface EvalRunItem {
  testset_item_id: string;
  query: string | null;
  hit_rank: number | null;
  evidence_ranks?: number[] | null;
  recall: number;
  map: number | null;
  latency_ms: number;
  evidence_total?: number;
  evidence_matched?: number;
  evidence_coverage?: number;
  channels?: EvalChannelScore[];
  answer_document_id?: string;
  answer_chunk_index?: number;
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
