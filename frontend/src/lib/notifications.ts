import { toast } from 'vue-sonner'
export { toast }
const shownErrors = new WeakSet<object>()
export function notifyError(error: unknown, fallback = '요청을 처리하지 못했습니다.') {
  if (error && typeof error === 'object') {
    if (shownErrors.has(error)) return
    shownErrors.add(error)
  }
  const message =
    error instanceof Error ? error.message : typeof error === 'string' ? error : fallback
  toast.error(message, { id: 'error:' + message })
}
const NOTICE_KEY = 'disclosure-check.notice'
export function queueNotice(message: string) {
  try {
    sessionStorage.setItem(NOTICE_KEY, message)
  } catch {
    toast.success(message)
  }
}
export function showQueuedNotice() {
  try {
    const message = sessionStorage.getItem(NOTICE_KEY)
    sessionStorage.removeItem(NOTICE_KEY)
    if (message) toast.success(message)
  } catch {
    /* 저장소가 차단된 경우 현재 화면의 알림을 유지합니다. */
  }
}
