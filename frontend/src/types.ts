export type DocumentStatus = 'pending' | 'success' | 'failed';

export type GraphStatus = 'none' | 'pending' | 'queue' | 'success' | 'failed';

export interface GraphState {
  status: GraphStatus;
  error: string | null;
}

export interface DocumentItem {
  id: string;
  name: string;
  status: DocumentStatus;
  graph?: GraphState | null;
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

export type ActiveView = 'search' | 'documents' | 'evaluation' | 'graph';

export interface TargetChunkLink {
  documentId: string;
  chunkIndex?: number;
  documentName?: string;
  chunkText?: string;
}

// ----------------------------------------------------
// Graph Explorer Types
// ----------------------------------------------------

export interface GraphEntityCard {
  name_norm: string;
  name: string;
  type: string;
  description?: string;
  degree: number;
  evidence_count: number;
}

export interface GraphNeighborhoodNode {
  name_norm: string;
  name: string;
  type: string;
  hops: number;
  evidence_count: number;
}

export interface GraphNeighborhoodEdge {
  src: string;
  dst: string;
  type: string;
  evidence: string[]; // ["doc_id:chunk_index", ...]
}

export interface GraphNeighborhoodResponse {
  nodes: GraphNeighborhoodNode[];
  edges: GraphNeighborhoodEdge[];
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

export interface EvidenceChunkRef {
  document_id: string;
  chunk_index: number;
}

export interface EvidenceGroup {
  chunks: EvidenceChunkRef[];
}

export interface TestSetItem {
  id: string;
  query?: string | null;
  status: EvalItemStatus;
  error_message?: string | null;
  document_name?: string;
  context_text?: string;
  evidence: EvidenceChunkRef[];
  answer_document_id?: string;
  answer_chunk_index?: number;
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
  chunks?: EvidenceChunkRef[];
  groups?: EvidenceGroup[];
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
  graph?: boolean;
}

export interface EvalRunBucketSummary {
  [key: string]: number | undefined;
  evidence_coverage?: number;
  queries?: number;
}

export interface EvalRunMetrics {
  [key: string]: any;
  avg_latency_ms?: number;
  evidence_coverage?: number;
  queries?: number;
  buckets?: {
    single_hop: EvalRunBucketSummary;
    multi_hop: EvalRunBucketSummary;
  };
}

export interface EvalRunItem {
  testset_item_id: string;
  query: string | null;
  hit_rank: number | null;
  evidence_ranks?: number[] | null;
  // 块级全中（0/1）——与聚合 recall@k 同名同义（文档级宽口径与 low_recall/joint_hit 已退役）
  recall: number;
  map: number | null;
  latency_ms: number;
  evidence_total?: number;
  evidence_matched?: number;
  evidence_coverage?: number;
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

