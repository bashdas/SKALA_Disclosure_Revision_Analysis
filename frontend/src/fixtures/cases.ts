import type {
  Company,
  Filing,
  Memo,
  AnalysisTask,
  ReviewReport,
  Perspective,
} from '../types/domain'

export const companies: Company[] = [
  {
    id: 'lnf',
    name: '엘앤에프',
    code: '066970',
    sector: '이차전지 소재',
    initials: 'L&F',
    description: '양극재 공급계약의 변화와 성장 가정을 함께 확인합니다.',
  },
  {
    id: 'shi',
    name: '삼성중공업',
    code: '010140',
    sector: '조선·해양',
    initials: 'SHI',
    description: '수주·실적·계약 위험을 기존 리서치와 연결합니다.',
  },
  {
    id: 'samsung-electronics',
    name: '삼성전자',
    code: '005930',
    sector: '반도체·전자',
    initials: 'SEC',
    description: '반도체·전자 업종의 공시와 메모를 확인하는 샘플입니다.',
  },
  {
    id: 'sk-hynix',
    name: 'SK하이닉스',
    code: '000660',
    sector: '반도체',
    initials: 'SKH',
    description: '메모리 반도체 관련 리서치 자료를 확인하는 샘플입니다.',
  },
  {
    id: 'hyundai-motor',
    name: '현대차',
    code: '005380',
    sector: '자동차',
    initials: 'HMC',
    description: '자동차 업종의 공시와 리서치 자료를 확인하는 샘플입니다.',
  },
  {
    id: 'kia',
    name: '기아',
    code: '000270',
    sector: '자동차',
    initials: 'KIA',
    description: '자동차 사업 관련 공시와 메모를 모아보는 샘플입니다.',
  },
  {
    id: 'lg-energy-solution',
    name: 'LG에너지솔루션',
    code: '373220',
    sector: '이차전지',
    initials: 'LGES',
    description: '배터리 업종의 공시와 분석 자료를 확인하는 샘플입니다.',
  },
  {
    id: 'samsung-biologics',
    name: '삼성바이오로직스',
    code: '207940',
    sector: '바이오·의약품',
    initials: 'SBL',
    description: '바이오의약품 관련 공시와 메모를 확인하는 샘플입니다.',
  },
  {
    id: 'naver',
    name: 'NAVER',
    code: '035420',
    sector: '인터넷·플랫폼',
    initials: 'N',
    description: '인터넷 플랫폼 관련 리서치 자료를 확인하는 샘플입니다.',
  },
  {
    id: 'kb-financial',
    name: 'KB금융',
    code: '105560',
    sector: '금융',
    initials: 'KB',
    description: '금융 업종의 공시와 분석 자료를 확인하는 샘플입니다.',
  },
  {
    id: 'lg-chem',
    name: 'LG화학',
    code: '051910',
    sector: '화학·소재',
    initials: 'LG',
    description: '화학·소재 업종의 공시와 메모를 확인하는 샘플입니다.',
  },
  {
    id: 'hanwha-aerospace',
    name: '한화에어로스페이스',
    code: '012450',
    sector: '방산·항공우주',
    initials: 'HA',
    description: '방산·항공우주 관련 리서치 자료를 확인하는 샘플입니다.',
  },
]
export const filings: Filing[] = [
  {
    id: 'filing-lnf',
    companyId: 'lnf',
    receiptNo: null,
    title: '[기재정정] 단일판매·공급계약체결',
    filingType: '계약금액 변경',
    filedAt: '2025-12-29T17:00:00+09:00',
    currentVersion: 2,
    eventGroup: 'tesla',
    sourceUrl: 'https://www.newspim.com/news/view/20251230000237',
    versions: [
      {
        version: 1,
        createdAt: '2023-02-28T12:00:00+09:00',
        rawContent:
          '시연용 원공시 요약 · 실제 공시 원문이 아닙니다.\n\n계약 상대방: 테슬라\n공급 품목: 하이니켈 양극재\n계약금액: 약 3조8,347억원\n공급기간: 2024년부터 2025년까지\n\n원계약과 정정공시의 변경 전후를 비교하기 위한 샘플입니다.',
      },
      {
        version: 2,
        createdAt: '2025-12-29T17:00:00+09:00',
        rawContent:
          '시연용 정정표 요약 · 실제 공시 원문이 아닙니다.\n\n정정 항목: 계약금액\n변경 전: 약 3조8,347억원\n변경 후: 9,730,316원(약 973만원)\n정정 사유: 공급물량 변경에 따른 계약금액 조정\n\n접수번호와 정확한 접수 시각은 이 샘플에서 확인하지 않았습니다. 기사에 기재된 발표일을 사용하며 분석 시점은 당일 종료 기준입니다.',
      },
    ],
  },
  {
    id: 'filing-shi-1',
    companyId: 'shi',
    receiptNo: '20250618800387',
    title: '단일판매·공급계약해지 · 관련 계약 ①',
    filingType: '계약 해지',
    filedAt: '2025-06-18T15:34:04+09:00',
    currentVersion: 1,
    eventGroup: 'zvezda',
    sourceUrl: 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250618800387',
    versions: [
      {
        version: 1,
        createdAt: '2025-06-18T15:34:04+09:00',
        rawContent:
          '시연용 해지 공시 요약 · 실제 공시 원문이 아닙니다.\n\n접수번호: 20250618800387\n계약내용: 블록, 기자재 및 설계\n해지금액: 약 2조453억원\n계약상대: 유라시아 지역 선주\n회사 기재 사유: 선주사의 위법한 계약해지\n\n해지 사유는 회사 측의 설명으로, 법적 책임이 확정됐다는 의미가 아닙니다. 관련 공시 ②는 별도 계약으로 연결합니다.',
      },
    ],
  },
  {
    id: 'filing-shi-2',
    companyId: 'shi',
    receiptNo: '20250618800388',
    title: '단일판매·공급계약해지 · 관련 계약 ②',
    filingType: '계약 해지',
    filedAt: '2025-06-18T15:34:05+09:00',
    currentVersion: 1,
    eventGroup: 'zvezda',
    sourceUrl: 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250618800388',
    versions: [
      {
        version: 1,
        createdAt: '2025-06-18T15:34:05+09:00',
        rawContent:
          '시연용 관련 공시 요약 · 실제 공시 원문이 아닙니다.\n\n접수번호: 20250618800388\n관련 사건: 즈베즈다 공급계약 해지\n두 해지 공시의 합계 규모: 약 4조8천억원\n\n이 문서는 관련 계약 ①과 별도의 공시입니다. 개별 해지금액과 정확한 접수 시각은 실제 원문을 확인해야 합니다. 표시 시각은 시연 순서용입니다.',
      },
    ],
  },
]
export const memos: Memo[] = [
  {
    id: 'memo-lnf',
    companyName: '엘앤에프',
    title: '테슬라향 공급과 양극재 성장 가정',
    currentVersion: 2,
    createdAt: '2025-05-12T09:00:00+09:00',
    updatedAt: '2025-11-20T09:00:00+09:00',
    versions: [
      {
        version: 1,
        content:
          '테슬라와의 양극재 공급계약을 중장기 성장의 근거로 검토한다.\n\n계약 규모와 실제 납품·매출 인식은 구분해서 확인해야 한다.',
        createdAt: '2025-05-12T09:00:00+09:00',
        originalFilename: '엘앤에프_성장가정_v1.txt',
        sizeBytes: null,
        contentHash: null,
      },
      {
        version: 2,
        content:
          '테슬라향 공급 확대가 향후 양극재 매출 성장에 기여할 것으로 가정한다.\n\n해당 계약의 연도별 매출 기여액과 실제 납품 실적은 추가 확인이 필요하다.\n\n단일 고객의 계약 변화를 이차전지 산업 전체의 수요 변화로 일반화하지 않는다.',
        createdAt: '2025-11-20T09:00:00+09:00',
        originalFilename: '엘앤에프_성장가정_v2.txt',
        sizeBytes: null,
        contentHash: null,
      },
    ],
  },
  {
    id: 'memo-shi',
    companyName: '삼성중공업',
    title: '러시아 프로젝트와 수주·환헤지 점검',
    currentVersion: 1,
    createdAt: '2025-03-20T09:00:00+09:00',
    updatedAt: '2025-03-20T09:00:00+09:00',
    versions: [
      {
        version: 1,
        content:
          '러시아 프로젝트의 계약 수행 여부를 수주잔고와 향후 매출 전망의 검토 요인으로 둔다.\n\n관련 선물환 회계처리 변경에 따른 손실은 2024년 4분기에 이미 반영된 것으로 확인한다.\n\n선수금 반환 요구와 최종 지급 의무는 구분하며, 추가 현금 부담은 분쟁 결과와 후속 공시를 확인한다.',
        createdAt: '2025-03-20T09:00:00+09:00',
        originalFilename: '삼성중공업_리스크점검_v1.txt',
        sizeBytes: null,
        contentHash: null,
      },
    ],
  },
]
export function perspectives(companyId: string): Perspective[] {
  return [
    {
      type: 'BUSINESS_INDUSTRY',
      selected: true,
      selectionReason: '계약이 기존 성장·수주 논리에 미치는 영향을 확인합니다.',
      question: '기존 사업 가정은 유지할 수 있는가?',
      status: 'REGISTERED',
      result: null,
    },
    {
      type: 'FINANCE',
      selected: true,
      selectionReason: '계약금액과 실적 영향, 기반영 여부를 구분합니다.',
      question: '기존 전망에 중복 반영될 항목이 있는가?',
      status: 'REGISTERED',
      result: null,
    },
    {
      type: 'EXTERNAL_RISK',
      selected: companyId === 'shi',
      selectionReason:
        companyId === 'shi'
          ? '제재·계약 분쟁과 수금 조건의 확인이 필요합니다.'
          : '기본 계약 비교에 집중합니다. 외부 환경의 원인은 별도 근거가 없어 판단하지 않습니다.',
      question: '외부 조건이 계약 이행에 영향을 주는가?',
      status: 'REGISTERED',
      result: null,
    },
  ]
}
export function buildReport(task: AnalysisTask, memo: Memo, filing: Filing): ReviewReport {
  const version = memo.versions.find((v) => v.version === task.baseMemoVersion)!
  const paragraphs = version.content.split(/\n\s*\n/).filter(Boolean)
  const shi = task.companyId === 'shi'
  const gap = task.scenario === 'evidence-gap' || task.scenario === 'limit'
  const statement = shi
    ? '기반영 손실과 추가 영향은 구분해야 합니다.'
    : '계약금액의 변경과 당기 실적 영향은 구분해야 합니다.'
  const report: ReviewReport = {
    id: `report-${task.id}`,
    taskId: task.id,
    version: 1,
    title: shi ? '즈베즈다 계약 해지 · 기존 가정 점검' : '테슬라 공급계약 변경 · 성장 가정 점검',
    generatedAt: new Date().toISOString(),
    savedAt: null,
    summary: shi
      ? '계약 해지는 수주·매출 가정의 재검토 사유입니다. 이미 반영된 파생상품 손실을 새 손실로 다시 차감하지 않고, 추가 현금 부담과 확정되지 않은 법적 의무를 구분합니다.'
      : '계약금액이 크게 축소됐으므로 테슬라향 성장 가정을 재검토합니다. 계약금액 감소분 전체를 당기 매출·이익 감소액으로 적용하지 않으며, 실제 납품과 기존 추정 반영 여부는 별도로 확인합니다.',
    changes: shi
      ? [
          { label: '계약 상태', before: '공급계약', after: '계약 해지 공시' },
          { label: '관련 공시', before: '각 원계약', after: '해지 공시 2건 · 개별 구분' },
        ]
      : [
          { label: '계약금액', before: '약 3조8,347억원', after: '약 973만원' },
          { label: '변경 사유', before: '당초 공급계획', after: '공급물량 변경' },
        ],
    findings: [
      {
        id: `${task.id}-growth`,
        beforeText: paragraphs[0] || '',
        memoParagraph: 0,
        newFact: shi
          ? '관련 계약의 해지 공시가 제출됐습니다.'
          : '계약금액이 약 973만원으로 정정됐습니다.',
        impactType: 'INTERPRETATION_REVIEW',
        reason:
          '기존 메모의 사업 가정에 영향을 주는 사실입니다. 정량 실적 추정표가 없어 매출 수정액은 산출하지 않습니다.',
        suggestion: shi
          ? '계약이 기존 매출·수주 전망에서 이미 제외됐는지 확인합니다.'
          : '테슬라향 매출 기여 가정을 실제 공급 실적과 대조합니다.',
        evidenceIds: ['memo-source', 'filing-source'],
      },
      {
        id: `${task.id}-accounting`,
        beforeText: paragraphs[1] || paragraphs[0] || '',
        memoParagraph: paragraphs[1] ? 1 : 0,
        newFact: statement,
        impactType: shi ? 'NO_IMPACT' : 'HOLD',
        reason: shi
          ? '샘플 기준 메모에 기존 손실 반영이 명시돼 있습니다. 이 항목의 유지 판단이며, 계약 해지 전체에 추가 영향이 없다는 뜻은 아닙니다.'
          : '계약금액만으로 실제 매출·이익 감소액을 확정할 수 없습니다. 기존 추정표와 납품 실적이 필요합니다.',
        suggestion: shi
          ? '이미 반영한 손실은 다시 차감하지 않고 추가 손익·현금 부담을 별도로 검토합니다.'
          : '실제 공급 실적과 기존 전망 반영액을 추가 확보합니다.',
        evidenceIds: shi
          ? ['memo-finance-source', 'prior-source']
          : ['memo-finance-source', 'filing-source'],
      },
    ],
    evidence: [
      {
        id: 'memo-source',
        title: `${memo.title} · 시연용 메모`,
        kind: 'memo',
        publishedAt: version.createdAt,
        quote: paragraphs[0] || '',
        context: version.content,
        url: null,
        documentId: memo.id,
        version: version.version,
        paragraph: 0,
        location: `v${version.version} · 본문 문단`,
      },
      {
        id: 'memo-finance-source',
        title: `${memo.title} · 재무 가정`,
        kind: 'memo',
        publishedAt: version.createdAt,
        quote: paragraphs[1] || paragraphs[0] || '',
        context: version.content,
        url: null,
        documentId: memo.id,
        version: version.version,
        paragraph: paragraphs[1] ? 1 : 0,
        location: `v${version.version} · 문단 ${paragraphs[1] ? 2 : 1}`,
      },
      {
        id: 'filing-source',
        title: `${filing.title} · 시연용 요약`,
        kind: 'filing',
        publishedAt: filing.filedAt,
        quote: shi
          ? '계약내용: 블록, 기자재 및 설계. 계약 해지 사유는 회사 측 설명입니다.'
          : '변경 전: 약 3조8,347억원 / 변경 후: 9,730,316원',
        context: filing.versions.find((v) => v.version === filing.currentVersion)!.rawContent,
        url: filing.receiptNo ? filing.sourceUrl : null,
        documentId: filing.id,
        version: filing.currentVersion,
        paragraph: null,
        location: `공시 요약 v${filing.currentVersion}`,
      },
    ],
    warnings: [
      shi
        ? '선수금 반환 요구와 최종 지급 의무는 다릅니다. 비공개 중재 결과와 계약별 헤지 조건은 미확인입니다.'
        : '고객별 납품·매출 실적과 기존 정량 추정표가 없어 실적 수정액을 계산하지 않습니다.',
    ],
    noAdditionalAnalysisReason: shi
      ? null
      : '외부 환경·위험은 추가 근거가 없어 실행하지 않았습니다. 원인이나 산업 전체의 수요를 단정하지 않습니다.',
  }
  if (shi) {
    report.evidence.push({
      id: 'prior-source',
      title: '하나증권 · 2025년 2월 6일 리서치',
      kind: 'external',
      publishedAt: '2025-02-06T00:00:00+09:00',
      quote:
        '러시아 프로젝트 관련 선물환 회계처리 변경과 파생상품 평가손실을 설명합니다. (시연용 요약)',
      context:
        '공시 기준 시점보다 앞서 공개된 분석입니다. 실제 손실 항목과 금액은 보고서 원문 및 재무제표 주석에서 확인해야 합니다. 해지 공시 이후 새로 발생한 손실로 중복 반영하지 않습니다.',
      url: 'https://www.hanaw.com/download/research/FileServer/WEB/info/daily/2025/02/05/Daily_250206.pdf#page=10',
      documentId: null,
      version: null,
      paragraph: null,
      location: 'PDF 10쪽 · 기업분석',
    })
    report.evidence.push({
      id: 'related-filing',
      title: '즈베즈다 관련 해지 공시 · 별도 계약',
      kind: 'filing',
      publishedAt: filing.filedAt,
      quote: '동일 사건의 관련 공시이며 개별 계약으로 구분합니다.',
      context: '해지 공시 2건을 중복으로 더하지 않고, 각 원계약과 연결해 확인해야 합니다.',
      url:
        'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' +
        (filing.id === 'filing-shi-1' ? '20250618800388' : '20250618800387'),
      documentId: filing.id === 'filing-shi-1' ? 'filing-shi-2' : 'filing-shi-1',
      version: 1,
      paragraph: null,
      location: '관련 공시 · 별도 접수번호',
    })
  }
  if (gap) {
    report.warnings.push(
      task.scenario === 'limit'
        ? '시연 시나리오: 추가 조회 한도에 도달했습니다. 해당 항목은 판단 보류합니다.'
        : '시연 시나리오: 추가 근거를 확보하지 못했습니다. 해당 항목은 판단 보류합니다.',
    )
    report.findings[0]!.impactType = 'HOLD'
  }
  if (memo.companyName === null || memo.id.startsWith('uploaded-')) {
    report.warnings.push(
      '업로드 메모의 실제 작성일과 내용의 적합성은 미확인입니다. 종목 연결은 내용 검증을 의미하지 않습니다. 시연은 선택한 사례의 고정된 설명을 사용하며 자유 텍스트를 실제로 분석하지 않습니다.',
    )
    report.findings.forEach((f) => {
      f.impactType = 'HOLD'
      f.reason =
        '내용·작성 시점이 검증되지 않은 업로드 메모입니다. 시연만 수행하며 논리의 유지 여부를 확정하지 않습니다.'
    })
  }
  return report
}

export function seedTasks(): { tasks: AnalysisTask[]; reports: ReviewReport[] } {
  const tasks: AnalysisTask[] = [],
    reports: ReviewReport[] = []
  for (const [id, companyId, status, scenario] of [
    ['sample-lnf', 'lnf', 'COMPLETED_WITH_WARNINGS', 'normal'],
    ['sample-shi', 'shi', 'COMPLETED_WITH_WARNINGS', 'evidence-gap'],
    ['sample-save-failed', 'shi', 'SAVE_FAILED', 'save-failure'],
    ['sample-analysis-failed', 'lnf', 'FAILED', 'analysis-failure'],
  ] as const) {
    const memo = memos.find(
      (m) => m.companyName === companies.find((c) => c.id === companyId)!.name,
    )!
    const filing = filings.find((f) =>
      id === 'sample-save-failed' ? f.id === 'filing-shi-2' : f.companyId === companyId,
    )!
    const time = companyId === 'shi' ? '2025-06-18T16:20:00+09:00' : '2025-12-29T18:20:00+09:00'
    const task: AnalysisTask = {
      id,
      companyId,
      filingId: filing.id,
      memoId: memo.id,
      baseMemoVersion: memo.currentVersion,
      status,
      scenario,
      currentStage: status === 'FAILED' ? 'INPUT_COLLECTION' : 'REPORT_SAVE',
      asOf: companyId === 'shi' ? '2025-06-18T15:34:04+09:00' : '2025-12-29T23:59:59+09:00',
      createdAt: time,
      startedAt: time,
      completedAt: status === 'SAVE_FAILED' ? null : time,
      errorMessage:
        status === 'FAILED'
          ? '자료 조회 단계에서 중단된 시연 작업입니다. 실제 외부 API를 호출하지 않았습니다.'
          : status === 'SAVE_FAILED'
            ? '생성된 결과는 유지되지만 저장이 완료되지 않았습니다.'
            : null,
      errorStage:
        status === 'FAILED' ? 'INPUT_COLLECTION' : status === 'SAVE_FAILED' ? 'REPORT_SAVE' : null,
      hasWarnings: status !== 'FAILED',
      sequence: 7,
      perspectives: perspectives(companyId).map((p) => ({
        ...p,
        status: p.selected ? 'COMPLETED' : 'REGISTERED',
        result: p.selected ? '시연용 분석 결과입니다. 관련 가정과 근거를 함께 확인하세요.' : null,
      })),
    }
    if (scenario === 'evidence-gap') task.perspectives[2]!.status = 'INSUFFICIENT_EVIDENCE'
    tasks.push(task)
    if (status !== 'FAILED') {
      const report = buildReport(task, memo, filing)
      report.generatedAt = time
      report.savedAt = status === 'SAVE_FAILED' ? null : time
      reports.push(report)
    }
  }
  return { tasks, reports }
}
