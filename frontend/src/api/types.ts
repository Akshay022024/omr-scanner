/**
 * Types mirroring ARCHITECTURE.md §6 (engine JSON) and §7 (REST API).
 * Where the doc does not pin a shape down (batch summary, health, benchmark report,
 * template list), the types are deliberately permissive and the UI reads them defensively.
 */

/** IDs are treated as opaque. The backend may send strings (UUID) or integers. */
export type Id = string | number;

export type ScanStatus = 'ok' | 'needs_review' | 'failed';
export type FieldState = 'single' | 'blank' | 'multiple' | 'ambiguous';
export type PaperSet = 'A' | 'B' | 'C';
export const PAPER_SETS: readonly PaperSet[] = ['A', 'B', 'C'];
export const OPTIONS = ['A', 'B', 'C', 'D'] as const;
export type Option = (typeof OPTIONS)[number];
export type QuestionGrade = 'correct' | 'wrong' | 'blank' | 'multiple' | 'no_key';

export interface FieldResult {
  id: string; // "q3", "roll_6", "paper_set"
  group: string; // "answers" | "roll_no" | "paper_set"
  question?: number | null;
  state: FieldState;
  value: string; // "" blank, "AC" multiple
  confidence?: number | null;
  scores?: Record<string, number>;
}

export interface Registration {
  method?: string | null; // ecc | orb | anchors | identity
  quality?: number | null; // 0..1
  homography?: number[][] | null;
}

export interface ScanResult {
  template_id: string;
  status: ScanStatus;
  error?: string | null;
  roll_no?: string | null;
  paper_set?: string | null;
  answers: Record<string, string>;
  fields: FieldResult[];
  review_flags: string[];
  registration?: Registration | null;
  threshold?: number | null;
  aligned_size?: [number, number] | null;
  timings_ms?: Record<string, number> | null;
}

export interface GradeResult {
  answer_key_id: Id;
  paper_set_used?: string | null;
  score: number;
  max_score: number;
  correct: number;
  wrong: number;
  blank: number;
  multiple: number;
  per_question: Record<string, QuestionGrade>;
}

export interface ScanRecord {
  id: Id;
  batch_id: Id;
  filename: string;
  page?: number | null;
  created_at?: string | null;
  /** Answer key the scan is graded with (set on upload or by regrade). */
  answer_key_id?: Id | null;
  result: ScanResult;
  grade?: GradeResult | null;
  corrected?: boolean;
}

export interface UploadResponse {
  batch_id: Id;
  scans: ScanRecord[];
}

export interface ScanPatch {
  roll_no?: string;
  paper_set?: string | null;
  answers?: Record<string, string>;
}

export type AnswerKeySets = Partial<Record<PaperSet, Record<string, string>>>;

export interface AnswerKey {
  id: Id;
  name: string;
  template_id: string;
  keys: AnswerKeySets;
  marks_correct: number;
  marks_wrong: number;
  marks_blank: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export type AnswerKeyInput = Omit<AnswerKey, 'id' | 'created_at' | 'updated_at'>;

/** GET /api/batches and /api/batches/{id}: shape not fixed by the doc, so it is read defensively. */
export interface BatchSummary {
  id: Id;
  created_at?: string | null;
  template_id?: string | null;
  answer_key_id?: Id | null;
  scan_count?: number | null;
  count?: number | null;
  needs_review?: number | null;
  review_count?: number | null;
  failed?: number | null;
  mean_score?: number | null;
  avg_score?: number | null;
  corrected_count?: number | null;
  status_counts?: Partial<Record<ScanStatus, number>> | null;
  scans?: ScanRecord[] | null;
  [extra: string]: unknown;
}

export interface TemplateSummary {
  id: string;
  name?: string | null;
  version?: number | null;
  num_questions?: number | null;
  options?: string[] | null;
  paper_sets?: string[] | null;
  [extra: string]: unknown;
}

export interface TemplateBubble {
  value: string;
  x: number;
  y: number;
  r: number;
}

export interface TemplateField {
  id: string;
  group: string;
  type?: string;
  question?: number;
  bubbles: TemplateBubble[];
}

/** GET /api/templates/{id}: template.json. */
export interface TemplateGeometry {
  id: string;
  name?: string;
  version?: number;
  page?: { width_px: number; height_px: number; dpi?: number; paper?: string };
  anchors?: Record<string, [number, number, number, number]>;
  num_questions?: number;
  options?: string[];
  fields: TemplateField[];
}

export interface Health {
  status?: string;
  engine_version?: string;
  version?: string;
  [extra: string]: unknown;
}

/** benchmarks/reports/latest.json: structure is read defensively (see lib/benchmark.ts). */
export type BenchmarkReport = Record<string, unknown>;
