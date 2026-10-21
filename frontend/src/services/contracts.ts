import type {
  AnalysisEvent,
  AnalysisTask,
  Company,
  Filing,
  Memo,
  ReviewReport,
  StartAnalysisInput,
  ReadReference,
} from '../types/domain'

export interface Services {
  companies: { list(): Promise<Company[]> }
  filings: { list(): Promise<Filing[]> }
  memos: {
    list(): Promise<Memo[]>
    upload(file: File, title?: string, companyId?: string): Promise<Memo>
  }
  analyses: {
    list(): Promise<AnalysisTask[]>
    reports(): Promise<ReviewReport[]>
    start(input: StartAnalysisInput): Promise<AnalysisTask>
    retrySave(taskId: string): Promise<AnalysisTask>
    subscribe(listener: (event: AnalysisEvent) => void): () => void
  }
  reads: { list(): Promise<string[]>; mark(ref: ReadReference): Promise<string> }
}
export const readKey = (ref: ReadReference) => `demo-ra:${ref.kind}:${ref.id}:v${ref.version}`
