export const MAX_MEMO_BYTES = 5 * 1024 * 1024
export async function readMemoFile(file: File): Promise<string> {
  if (!/\.txt$/i.test(file.name) || (file.type && file.type.toLowerCase() !== 'text/plain'))
    throw new Error('UTF-8 .txt 파일만 업로드할 수 있습니다.')
  if (file.size > MAX_MEMO_BYTES) throw new Error('파일은 5 MiB 이하여야 합니다.')
  let content: string
  try {
    content = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())
  } catch {
    throw new Error('UTF-8로 저장된 텍스트 파일인지 확인해 주세요.')
  }
  if (!content.trim()) throw new Error('내용이 비어 있는 메모는 업로드할 수 없습니다.')
  if (content.includes('\0')) throw new Error('사용할 수 없는 NUL 문자가 포함돼 있습니다.')
  return content
}
