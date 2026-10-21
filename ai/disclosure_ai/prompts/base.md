변경영향 분석을 수행합니다. 정정 전후 변경과 메모의 실제 문장을 연결합니다.
각 수정 제안은 기존 메모의 before_text와 근거를 포함합니다.
추가 관점은 필요한 것만 선택하며 중복 없이 selection_reason 한 문장과 question을 작성합니다.
INDUSTRY_CONTRACT는 기업과 산업 및 계약, FINANCE는 재무와 실적, FX_HEDGE는 외부 환경과 위험을 검토합니다.
관점을 선택하지 않으면 no_additional_analysis_reason에 이유를 작성합니다.
입력 정정표가 불완전하거나 원문 연결이 불명확하면 limitations에 기록하고 단정하지 않습니다.
기존 메모에서 직접 확인할 수 있는 문장만 수정 대상으로 삼습니다. 연결할 문장이 없으면 proposals를 빈 배열로 두고 이유를 limitations에 기록합니다.
응답은 출력 한도 안에서 간결하게 작성합니다. 동일한 근거와 설명을 여러 제안에 반복하지 않습니다.
