import { it, expect, vi } from 'vitest'
import { toast } from 'vue-sonner'
import { notifyError, queueNotice, showQueuedNotice } from './notifications'
vi.mock('vue-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
it('deduplicates the same error and restores a success notice once after navigation', () => {
 const error = new Error('서버 오류')
 notifyError(error)
 notifyError(error)
 expect(toast.error).toHaveBeenCalledTimes(1)
 queueNotice('비밀번호를 변경했습니다.')
 showQueuedNotice()
 showQueuedNotice()
 expect(toast.success).toHaveBeenCalledExactlyOnceWith('비밀번호를 변경했습니다.')
})
