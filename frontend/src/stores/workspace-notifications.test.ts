import { it, expect, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { toast } from 'vue-sonner'
import { services } from '../services'
import { useWorkspace } from './workspace'
import type { AnalysisTask } from '../types/domain'
vi.mock('vue-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }))
vi.mock('../services', () => ({ services: {
 companies: { list: vi.fn(async () => []) }, filings: { list: vi.fn(async () => []) },
 memos: { list: vi.fn(async () => []) }, reads: { list: vi.fn(async () => []) },
 analyses: { list: vi.fn(async () => []), reports: vi.fn(async () => []), subscribe: vi.fn(() => () => {}), start: vi.fn() },
} }))
it('announces analysis start and one completion, ignoring repeated and stale events', async () => {
 setActivePinia(createPinia())
 const store = useWorkspace()
 await store.initialize()
 expect(toast.success).not.toHaveBeenCalled()
 const active = { id: 'task', companyId: 'company', status: 'RUNNING', sequence: 1 } as AnalysisTask
 vi.mocked(services.analyses.start).mockResolvedValue(active)
 await store.start({filingId:'filing',memoId:'memo',memoVersion:1})
 expect(toast.success).toHaveBeenCalledWith('분석을 시작했습니다.', expect.any(Object))
 const receive = vi.mocked(services.analyses.subscribe).mock.calls[0]![0]
 const complete = {...active, status: 'COMPLETED' as const, sequence: 2}
 receive({task:complete})
 receive({task:complete})
 receive({task:active})
 expect(toast.success).toHaveBeenCalledTimes(2)
 expect(toast.success).toHaveBeenLastCalledWith('분석이 완료되었습니다.', expect.any(Object))
 expect(store.tasks[0]!.status).toBe('COMPLETED')
 receive({task:{...active,status:'FAILED',sequence:3,errorMessage:'분석 오류'}})
 expect(toast.error).toHaveBeenCalledWith('분석에 실패했습니다.', expect.any(Object))
 store.dispose()
})
