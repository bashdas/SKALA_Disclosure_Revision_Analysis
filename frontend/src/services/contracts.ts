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
  filings: { list(): Promise<Filing[]>; invalidate(): void }
  memos: {
    list(): Promise<Memo[]>
    get(id: string): Promise<Memo>
    remove(id: string): Promise<void>
    upload(file: File, title?: string, companyId?: string): Promise<Memo>
  }
  analyses: {
    list(): Promise<AnalysisTask[]>
    reports(): Promise<ReviewReport[]>
    start(input: StartAnalysisInput): Promise<AnalysisTask>
    subscribe(
      listener: (event: AnalysisEvent) => void,
      onError?: (message: string) => void,
    ): () => void
  }
  reads: { list(): Promise<string[]>; mark(ref: ReadReference): Promise<string> }
}
export const readKey = (ref: ReadReference) => `${ref.kind}:${ref.id}:v${ref.version}`
