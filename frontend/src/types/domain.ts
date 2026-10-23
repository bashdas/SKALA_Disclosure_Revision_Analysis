export type AnalysisStatus =
  | 'CREATED'
  | 'QUEUED'
  | 'RUNNING'
  | 'SAVING'
  | 'COMPLETED'
  | 'COMPLETED_WITH_WARNINGS'
  | 'SAVE_FAILED'
  | 'FAILED'
  | 'CANCELLED'
export const stages = [
  'REQUEST_VALIDATION',
  'INPUT_COLLECTION',
  'RAG_PREPARATION',
  'BASE_ANALYSIS',
  'PERSPECTIVE_ANALYSIS',
  'REPORT_GENERATION',
  'REPORT_SAVE',
] as const
export type AnalysisStage = (typeof stages)[number]
export type PerspectiveType = 'INDUSTRY_CONTRACT' | 'FINANCE' | 'FX_HEDGE'
export type PerspectiveStatus =
  'REGISTERED' | 'RUNNING' | 'COMPLETED' | 'INSUFFICIENT_EVIDENCE' | 'LIMIT_REACHED' | 'FAILED'
export type ImpactType =
  'FACT_UPDATE' | 'CALCULATION_UPDATE' | 'INTERPRETATION_REVIEW' | 'NO_IMPACT' | 'HOLD'
export type DocumentKind = 'filing' | 'memo' | 'report'

export interface Company {
  favorite?: boolean
  id: string
  name: string
  code: string
  sector: string
  initials: string
  description: string
}
export interface FilingVersion {
  version: number
  rawContent: string
  createdAt: string
}
export interface Filing {
  isCorrection: boolean
  originReceiptNo: string | null
  id: string
  companyId: string
  receiptNo: string | null
  title: string
  filingType: string
  filedAt: string
  currentVersion: number
  eventGroup: string
  sourceUrl: string
  versions: FilingVersion[]
}
export interface MemoVersion {
  version: number
  content: string
  createdAt: string
  originalFilename: string | null
  sizeBytes: number | null
  contentHash: string | null
}
export interface Memo {
  id: string
  companyName: string | null
  title: string
  currentVersion: number
  createdAt: string
  updatedAt: string
  versions: MemoVersion[]
}
export interface Perspective {
  type: PerspectiveType
  selected: boolean
  selectionReason: string
  question: string
  status: PerspectiveStatus
  result: string | null
}
export interface AnalysisTask {
  id: string
  companyId: string
  filingId: string
  memoId: string
  baseMemoVersion: number
  status: AnalysisStatus
  currentStage: AnalysisStage | null
  createdAt: string
  startedAt: string | null
  completedAt: string | null
  asOf: string
  perspectives: Perspective[]
  errorMessage: string | null
  errorStage: AnalysisStage | null
  hasWarnings: boolean
  sequence: number
}
export interface Evidence {
  id: string
  title: string
  kind: 'memo' | 'filing' | 'external'
  publishedAt: string
  quote: string
  context: string
  url: string | null
  documentId: string | null
  version: number | null
  paragraph: number | null
  location: string
}
export interface Finding {
  id: string
  beforeText: string
  newFact: string
  impactType: ImpactType
  reason: string
  suggestion: string
  evidenceIds: string[]
  memoParagraph: number | null
}
export interface ReviewReport {
  id: string
  taskId: string
  version: number
  title: string
  generatedAt: string
  savedAt: string | null
  summary: string
  content: string
  changes: { label: string; before: string; after: string }[]
  perspectiveDecisions?: { type: Perspective['type']; selected: boolean; reason: string }[]
  memoReview?: { status: 'KEEP' | 'HOLD'; reason: string; evidenceIds: string[] }
  reviewPoints?: ReviewPoint[]
  findings: Finding[]
  evidence: Evidence[]
  warnings: string[]
  noAdditionalAnalysisReason: string | null
}
export interface ReviewPoint {
  perspectiveType: PerspectiveType
  title: string
  memoView: string
  disclosureFact: string
  reason: string
  question: string
  checkItems: string[]
  evidenceIds: string[]
}
export interface StartAnalysisInput {
  filingId: string
  memoId: string
  memoVersion: number
}
export interface AnalysisEvent {
  task: AnalysisTask
  report?: ReviewReport
}
export interface ReadReference {
  kind: DocumentKind
  id: string
  version: number
}

export const perspectiveLabels: Record<PerspectiveType, string> = {
  INDUSTRY_CONTRACT: '산업 및 계약',
  FINANCE: '재무,실적',
  FX_HEDGE: '환율 및 헤지',
}
export const stageLabels: Record<AnalysisStage, string> = {
  REQUEST_VALIDATION: '요청 확인',
  INPUT_COLLECTION: '자료 조회',
  RAG_PREPARATION: '근거 검색',
  BASE_ANALYSIS: '변경영향 분석',
  PERSPECTIVE_ANALYSIS: '관점별 분석',
  REPORT_GENERATION: '보고서 생성',
  REPORT_SAVE: '보고서 저장',
}
export const statusLabels: Record<AnalysisStatus, string> = {
  CREATED: '접수',
  QUEUED: '분석 대기',
  RUNNING: '분석 중',
  SAVING: '저장 중',
  COMPLETED: '저장 완료',
  COMPLETED_WITH_WARNINGS: '주의사항 있음',
  SAVE_FAILED: '저장 실패',
  FAILED: '분석 실패',
  CANCELLED: '취소',
}
export const impactLabels: Record<ImpactType, string> = {
  FACT_UPDATE: '사실 수정',
  CALCULATION_UPDATE: '계산값 수정',
  INTERPRETATION_REVIEW: '해석 재검토',
  NO_IMPACT: '영향 없음',
  HOLD: '판단 보류',
}
export const perspectiveStatusLabels: Record<PerspectiveStatus, string> = {
  REGISTERED: '대기',
  RUNNING: '분석 중',
  COMPLETED: '완료',
  INSUFFICIENT_EVIDENCE: '근거 부족',
  LIMIT_REACHED: '조회 한도 도달',
  FAILED: '실패',
}
export const activeStatuses: AnalysisStatus[] = [
  'CREATED',
  'QUEUED',
  'RUNNING',
  'SAVING',
  'SAVE_FAILED',
]
