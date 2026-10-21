export function date(value: string | null | undefined, withTime = false) {
  if (!value) return '미제공'
  return new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    ...(withTime ? { hour: '2-digit', minute: '2-digit', hour12: false } : {}),
  }).format(new Date(value))
}

export function disclosureUrl(receipt: string) {
  const sec = /^SEC:([0-9]{1,10}):([0-9]{10}-[0-9]{2}-[0-9]{6})$/.exec(receipt)
  return sec
    ? `https://www.sec.gov/Archives/edgar/data/${Number(sec[1])}/${sec[2]!.replaceAll('-', '')}/${sec[2]}-index.html`
    : `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${receipt}`
}
