# External MCP MVP — OpenDART

공식 외부 자료 조회 → 결정적 parsing → 구조화된 결과를 제공하는 Adapter입니다.
LLM·정정 영향 판단·Report 생성·DB·RAG·Worker 코드를 포함하지 않습니다.

MCP Python SDK v1/FastMCP (`mcp>=1.12,<2`, 테스트 1.30.0), Streamable HTTP `/mcp`,
stateless/JSON 응답을 사용합니다. `/health`는 process liveness이며 외부 API readiness가 아닙니다.
Tool은 **get_disclosure(receipt_no)** 하나입니다.

## 공식 명세와 조회 흐름

- [공시서류원본파일 공식 가이드](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019003)
- [공시검색 공식 가이드](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001)

1. receipt_no가 14자리 ASCII 숫자인지 검증합니다.
2. `GET https://opendart.fss.or.kr/api/document.xml`에 `crtfc_key`와 `rcept_no` query를 전달합니다.
   이름이 .xml이어도 정상 원문 응답은 ZIP binary이며, API 오류는 result/status/message XML입니다.
3. ZIP의 XML/HTML 파일을 안전하게 읽어 한국어 plain text, heading/section/표와 파일별 순서를 보존합니다.
4. `GET https://opendart.fss.or.kr/api/list.json`으로 메타데이터를 확보합니다.
   공식 검색 인자에 rcept_no 필터가 없으므로 그 이름의 인자를 임의로 추가하지 않습니다.
   번호 앞 8자리가 유효한 날짜라면 **단일 날짜 검색 힌트**로만 사용합니다.
   bgn_de=end_de=힌트, last_reprt_at=N, page_count=100으로 페이지를 순회하고,
   응답 list의 **rcept_no가 정확히 일치한 행만** 사용합니다.
5. 그 행의 corp_code/corp_name/report_nm/rcept_dt에서 회사·보고서·접수일을 반환합니다.
   검색 힌트를 filed_at이나 published_at으로 대신 반환하지 않습니다.

날짜 힌트가 실제 공시일과 다르거나 검색에 포함되지 않는 문서는 원문이 있어도 metadata가
없을 수 있습니다. 이때 각 metadata는 null이고 metadata_status=NOT_FOUND입니다.
기본 최대 100페이지를 넘기면 SEARCH_LIMIT_REACHED입니다. 회사명이나 날짜를 XML/파일명에서
추측해 채우지 않습니다. list API 호출 자체의 timeout/장애/인증 실패는 null 성공으로 숨기지 않습니다.

## 반환 계약

- receipt_no, corp_code, company_name, report_name, filed_at, metadata_status
- document: document_id=null, content_type=text/plain, text, tables, blocks, files, content_hash
- source: provider=OPENDART, source_type=REGULATORY_FILING, identifier=receipt_no,
  published_at=공식 rcept_dt 날짜, retrieved_at=UTC 조회 시각,
  original_location=`https://dart.fss.or.kr/dsaf001/main.do?rcpNo=<receipt_no>`

공식 document API는 별도 document_id를 제공하지 않아 null로 둡니다. files[].filename은 실제
ZIP member 이름이고 content_hash는 ZIP bytes의 SHA-256입니다. 이는 공식 문서 ID와 다릅니다.
filed_at/published_at은 날짜만 반환하며 제공되지 않은 시각을 만들어내지 않습니다.

## 기술적 Parser

lxml의 XML/HTML parser를 사용합니다. 기본 UTF-8이며 명시적 XML encoding/HTML charset은
엄격하게 decode합니다(EUC-KR 등). 조용한 replacement/회사 추론은 하지 않습니다.
외부 DTD 로딩·네트워크·entity 확장을 끄고 entity 선언/미해결 entity는 거부합니다.
HTML 형식은 실제 .html/.htm member에 한정하며 XML 오류를 HTML로 무조건 복구하지 않습니다.
script/style/head는 본문에서 제외합니다.

- blocks: ZIP member 순서와 DOM 순서의 heading/section/paragraph/table
- tables: 원래 row/cell 순서와 text, TH 여부, rowspan/colspan
- text: 일반 문단 줄바꿈 및 표의 행/셀 구분(줄바꿈/tab)

정정 전/후라는 원문 표기를 보존하지만 어느 값이 변경되었는지 판단하지 않습니다.
복잡한 중첩 표는 바깥 표의 cell text로 포함하며 완전한 시각적 레이아웃 재현은 하지 않습니다.
XML/HTML이 아닌 이미지/PDF/binary attachment는 parsing하지 않습니다. 파일을 디스크에 추출하지 않습니다.

다운로드 기본 20 MiB, 해제 총 64 MiB, 개별 member 32 MiB, ZIP entry 1000개로 제한합니다.
초과 원문을 잘라서 정상 문서로 반환하지 않습니다. PDF/OCR·chunking·embedding은 범위 밖입니다.

## 오류

MCP isError=true 결과의 JSON에 code/message/provider_status를 담습니다.
외부 원본 오류 메시지·body·URL exception은 반환하지 않습니다.

| code | 의미 |
| --- | --- |
| INVALID_RECEIPT_NO | 14자리 숫자 형식 오류 |
| DISCLOSURE_NOT_FOUND | 원문 API의 013/014: 데이터/파일 없음 |
| OPENDART_AUTH_FAILED | 키 미설정/형식, 010/011/012/901 또는 HTTP 401/403 |
| OPENDART_RATE_LIMITED | 020 또는 HTTP 429 |
| OPENDART_TIMEOUT | HTTP timeout |
| OPENDART_UNAVAILABLE | 연결/HTTP 장애·잘못된 metadata·그 밖의 API 오류 |
| DISCLOSURE_PARSE_FAILED | 손상 ZIP/XML/encoding·지원하지 않는 원문·안전 한도 초과 |

API XML의 013/014와 달리 HTTP 404 자체는 정상 빈 조회로 해석하지 않습니다.
Client는 lifespan 동안 한 AsyncClient를 재사용하고 종료 시 닫습니다. redirect/proxy 자동 사용 및
자동 retry는 없으며 요청마다 별도 Client를 만들지 않습니다.

## 환경변수와 실행

| 변수 | 기본값 |
| --- | --- |
| OPENDART_API_KEY | 로컬에서 발급받은 40자리 Key 설정 |
| OPENDART_BASE_URL | https://opendart.fss.or.kr/api |
| EXTERNAL_MCP_HOST | 0.0.0.0 |
| EXTERNAL_MCP_PORT | 8083 |
| EXTERNAL_MCP_REQUEST_TIMEOUT_SECONDS | 30 |
| OPENDART_MAX_DOWNLOAD_BYTES | 20971520 |
| OPENDART_METADATA_MAX_PAGES | 100 |
| MCP_ALLOWED_HOSTS | localhost:*, 127.0.0.1:*, external-mcp:* |

Key는 SecretStr이며 Tool argument가 아닙니다. OpenDART 명세상 query로 전달되므로 httpx/httpcore
URL 로그의 crtfc_key를 필터로 가립니다. 전체 원문/body/header는 로그에 dump하지 않습니다.
응답에도 configured key가 나타나면 방어적으로 redaction합니다. DB URL/INTERNAL_API_KEY는
설정 필드가 아니며 Compose에서도 전달하지 않습니다. MCP ingress 인증은 이 단계에 없으므로
신뢰된 내부 네트워크에서 사용하고 새 도메인은 MCP_ALLOWED_HOSTS에 명시합니다.

backend/.env.example을 참고해 로컬 backend/.env에 OpenDART Key를 설정한 뒤:

```bash
cd backend
docker compose up -d --build external-mcp
```

서비스에 depends_on이 없어 DB·Business API·Broker 없이 단독 기동됩니다.
Compose 내부 endpoint는 `http://external-mcp:8083/mcp`이며 host 포트는 공개하지 않습니다.

독립 실행은 external-mcp 폴더에서 Python 3.12 이상으로:

```bash
python -m pip install -e ../../shared -e '.[dev]'
export OPENDART_API_KEY='<로컬에서 발급받은 실제 Key>'
python -m app
```

## 검증

```bash
python -m pytest -q
```

Mock HTTP + MCP JSON-RPC 테스트이므로 외부 네트워크나 실제 Key를 사용하지 않습니다.
실제 OpenDART smoke test는 유효 Key·네트워크가 있을 때만 별도로 수행하며,
접수번호/성공 여부/metadata만 출력하고 원문과 Key를 출력하지 않습니다.
이 작업 환경에는 Key가 없어 **실제 OpenDART smoke test 미실행**입니다.
