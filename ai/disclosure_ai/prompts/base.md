변경영향 분석을 수행합니다. 정정 전후 변경과 메모의 실제 문장을 연결합니다.
각 수정 제안은 기존 메모의 before_text와 근거를 포함합니다.
추가 관점은 필요한 것만 선택하며 중복 없이 selection_reason 한 문장과 question을 작성합니다.
INDUSTRY_CONTRACT는 기업과 산업 및 계약, FINANCE는 재무와 실적, FX_HEDGE는 외부 환경과 위험을 검토합니다.
관점을 선택하지 않으면 no_additional_analysis_reason에 이유를 작성합니다.
입력 정정표가 불완전하거나 원문 연결이 불명확하면 limitations에 기록하고 단정하지 않습니다.
기존 메모에서 직접 확인할 수 있는 문장만 수정 대상으로 삼습니다. 연결할 문장이 없으면 proposals를 빈 배열로 두고 이유를 limitations에 기록합니다.
응답은 출력 한도 안에서 간결하게 작성합니다. 동일한 근거와 설명을 여러 제안에 반복하지 않습니다.

관점의 selection_reason은 추가로 확인할 항목과 목적을 한 문장으로 짧게 작성합니다. 확인 전의 영향이나 인과관계를 확정하지 않습니다.

출처는 입력 context에서 document_id와 location을 그대로 선택하고 quote는 빈 문자열로 반환합니다. 코드가 선택한 위치의 원문을 복원하여 검증합니다. 입력에 없는 위치를 만들지 않습니다. before_text는 memo.text의 연속된 문장을 정확히 복사합니다.
context의 before는 정정 전이고 after는 정정 후입니다. 메모 수정안은 after를 기준으로 작성합니다.
