import asyncio
import json
import os
import time
from pathlib import Path

import tiktoken
from langsmith.wrappers import wrap_openai
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, LengthFinishReasonError
from pydantic import ValidationError

from disclosure_ai.errors import LimitReached
from disclosure_ai.harness import lookup
from disclosure_ai.harness.ledger import Ledger
from disclosure_ai.harness.output import mask, review_output


class Harness:
    # 과거 원문 재분석과 네 관점 조회 후 보고서 검사를 마칠 시간을 확보합니다.
    RUN_SECONDS = 300
    ANALYSIS_TOKENS = 240000
    REPORT_TOKENS = 300000
    ANALYSIS_TURNS = 24
    REPORT_TURNS = 30

    def __init__(self, task_id: str, ledger: Ledger, call_model=None):
        self.task_id = task_id
        self.ledger = ledger
        self.call_model = call_model
        self.inflight = {}
        self.history_lock = asyncio.Lock()
        self.history_data = {}
        self.client = None
        self.guard = None
        # 인코딩 파일도 실행 산출물 경로에 보관합니다.
        os.environ.setdefault(
            "TIKTOKEN_CACHE_DIR",
            str(Path(os.environ.get("XDG_CACHE_HOME", "outputs/cache")) / "tiktoken"),
        )
        self.encoding = tiktoken.get_encoding("o200k_base")

    def remaining(self, report: bool = False) -> float:
        reserve = 0 if report else 60
        return self.RUN_SECONDS - reserve - (time.time() - self.ledger.row(self.task_id)["started"])

    async def reserve(self, tokens: int, report: bool = False, role: str = "") -> None:
        async with self.ledger.lock:
            row = self.ledger.row(self.task_id)
            role_counts = json.loads(row["tools"])
            if role.startswith("perspective:") and role_counts.get("model:" + role, 0) >= 5:
                raise LimitReached("관점별 모델 호출 한도에 도달했습니다.")
            ceiling = self.REPORT_TOKENS if report else self.ANALYSIS_TOKENS
            turns = self.REPORT_TURNS if report else self.ANALYSIS_TURNS
            if (
                self.remaining(report) <= 0
                or row["turns"] >= turns
                or row["tokens"] + tokens > ceiling
            ):
                raise LimitReached("실행 시간, 모델 턴 또는 토큰 한도에 도달했습니다.")
            self.ledger.db.execute(
                "UPDATE runs SET turns=turns+1,tokens=tokens+? WHERE id=?", (tokens, self.task_id)
            )
            if role:
                role_counts["model:" + role] = role_counts.get("model:" + role, 0) + 1
                self.ledger.db.execute(
                    "UPDATE runs SET tools=? WHERE id=?", (json.dumps(role_counts), self.task_id)
                )
            self.ledger.db.commit()

    def model_input_spec(self, role: str, context: dict, schema):
        prompts = Path(__file__).parents[1] / "prompts"
        system = (prompts / "common.md").read_text() + (prompts / f"{role}.md").read_text()
        if role == "base":
            kind = context.get("analysis_type", "UNKNOWN")
            if kind not in {"NEW", "CORRECTION", "UNKNOWN"}:
                kind = "UNKNOWN"
            system += (prompts / f"base_{kind.lower()}.md").read_text()
        if (
            role == "perspective"
            and context.get("selection", {}).get("perspective_type") == "MARKET_NEWS"
        ):
            system += (prompts / "market_news.md").read_text()
        input_limit, output_limit = (16000, 2500) if role == "perspective" else (20000, 4000)
        if context.get("history_context"):
            input_limit = 16000 if role == "perspective" else 24000
        if (
            role == "perspective"
            and context.get("selection", {}).get("perspective_type") == "MARKET_NEWS"
        ):
            input_limit = 16000
        if role == "output_check":
            input_limit = 24000
        schema_tokens = len(
            self.encoding.encode(json.dumps(schema.model_json_schema(), ensure_ascii=False))
        )
        available = input_limit - len(self.encoding.encode(system)) - schema_tokens - 100
        return system, input_limit, output_limit, schema_tokens, available

    def fits_model_input(self, role: str, context: dict, schema) -> bool:
        *_, available = self.model_input_spec(role, context, schema)
        return len(self.encoding.encode(mask(json.dumps(context, ensure_ascii=False)))) <= available

    async def model(self, role: str, context: dict, schema, report: bool = False):
        system, input_limit, output_limit, schema_tokens, available = self.model_input_spec(
            role, context, schema
        )
        content = mask(json.dumps(context, ensure_ascii=False))
        encoded = self.encoding.encode(content)
        if role == "output_check" and len(encoded) > available:
            raise LimitReached("출력 검사 문맥을 일부만 검사할 수 없습니다.")
        if len(encoded) > available:
            reduced = json.loads(content)
            reduced["context_truncated"] = True
            # 구조화 입력을 문자열 중간에서 자르면 메모와 출처 경계가 손실됩니다.
            while len(self.encoding.encode(json.dumps(reduced, ensure_ascii=False))) > available:
                lists, strings = [], []

                def candidates(value, lists=lists, strings=strings):
                    if isinstance(value, dict):
                        for key, item in value.items():
                            if isinstance(item, str) and len(item) > 256:
                                strings.append((len(item), value, key))
                            elif isinstance(item, (dict, list)):
                                candidates(item)
                    elif isinstance(value, list):
                        # 리포트 참조 분석은 출처 목록을 줄이면 공시나 리포트 전체가 사라질 수 있습니다.
                        # 문서 ID와 위치를 유지한 채 긴 본문을 줄여 각 자료의 근거를 남깁니다.
                        source_list = (
                            role in {"base", "research"}
                            and context.get("research_reports")
                            and all(
                                isinstance(item, dict)
                                and "document_id" in item
                                and "location" in item
                                for item in value
                            )
                        )
                        if len(value) > 1 and not source_list:
                            lists.append((len(json.dumps(value, ensure_ascii=False)), value))
                        for item in value:
                            candidates(item)

                candidates(reduced)
                if lists:
                    values = max(lists, key=lambda item: item[0])[1]
                    del values[max(1, len(values) // 2) :]
                elif strings:
                    length, parent, key = max(strings, key=lambda item: item[0])
                    parent[key] = parent[key][: length // 2]
                else:
                    raise LimitReached("고정 입력이 문맥 한도를 초과했습니다.")
            content = json.dumps(reduced, ensure_ascii=False)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        repair = False
        retries = 0
        while True:
            if self.guard:
                await self.guard(self.task_id)
            used_input = (
                sum(len(self.encoding.encode(m["content"])) for m in messages) + schema_tokens + 100
            )
            if used_input > input_limit:
                raise LimitReached("입력 토큰 한도에 도달했습니다.")
            if report and self.remaining(True) <= 10:
                raise LimitReached("보고서 저장 시간을 확보했습니다.")
            role_scope = (
                "perspective:" + context.get("selection", {}).get("perspective_type", "")
                if role in {"perspective", "news_plan"}
                else role
            )
            reserved = used_input + output_limit
            await self.reserve(reserved, report, role_scope)
            charged = used_input
            estimated = True
            started = time.monotonic()
            try:
                async with asyncio.timeout(min(45, self.remaining(report) - (10 if report else 0))):
                    if self.call_model:
                        answer = await self.call_model(role, context, schema)
                        parsed = schema.model_validate(answer)
                        actual = used_input + len(
                            self.encoding.encode(json.dumps(answer, ensure_ascii=False))
                        )
                    else:
                        if self.client is None:
                            self.client = wrap_openai(AsyncOpenAI(max_retries=0))
                        response = await self.client.chat.completions.parse(
                            model=os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"),
                            messages=messages,
                            max_completion_tokens=output_limit,
                            response_format=schema,
                        )
                        parsed = response.choices[0].message.parsed
                        if parsed is None:
                            raise ValueError("모델이 구조화 응답을 반환하지 않았습니다.")
                        actual = (
                            response.usage.total_tokens
                            if response.usage
                            else used_input + output_limit
                        )
                charged, estimated = actual, False
                self.ledger.event(
                    self.task_id,
                    "MODEL_END",
                    role=role,
                    tokens=actual,
                    elapsed=time.monotonic() - started,
                )
                return parsed
            except (ValidationError, ValueError, LengthFinishReasonError) as error:
                usage = getattr(getattr(error, "completion", None), "usage", None)
                if usage:
                    charged, estimated = usage.total_tokens, False
                self.ledger.event(self.task_id, "FORMAT_ERROR", role=role)
                if repair:
                    raise
                repair = True
                messages.append(
                    {
                        "role": "user",
                        "content": "출력 길이 한도 안에서 JSON을 완성합니다. 설명과 중복 인용을 줄이고 확인된 핵심 근거와 제한 사유를 보존합니다. 지정된 출력 구조를 지킵니다.",
                    }
                )
            except (APIConnectionError, APIStatusError, TimeoutError) as error:
                retryable = not isinstance(error, APIStatusError) or error.status_code in {
                    429,
                    500,
                    502,
                    503,
                    504,
                }
                self.ledger.event(
                    self.task_id, "MODEL_ERROR", role=role, error=type(error).__name__
                )
                if not retryable or retries >= 2:
                    raise
                retries += 1
                await asyncio.sleep(min(0.2 * retries, max(0, self.remaining(report))))
            finally:
                # 실패 응답의 사용량이 없으면 입력량을 추정 비용으로 남기고 미사용 출력 예약을 반환합니다.
                async with self.ledger.lock:
                    self.ledger.db.execute(
                        "UPDATE runs SET tokens=tokens+? WHERE id=?",
                        (charged - reserved, self.task_id),
                    )
                    self.ledger.db.commit()
                    self.ledger.event(self.task_id, "MODEL_BUDGET_SETTLED", role=role_scope,
                                      reserved=reserved, charged=charged, estimated=estimated)

    async def review_output(
        self, payload: dict, *, grounding=False, corrections=(), advisory=False,
        current_document_ids=(),
    ) -> tuple[dict, list[str]]:
        return await review_output(
            self, payload, grounding=grounding, corrections=corrections, advisory=advisory,
            current_document_ids=current_document_ids,
        )

    async def tool(self, name, args, invoke, *, report=False, scope=""):
        return await lookup.call(self, name, args, invoke, report=report, scope=scope)

    async def close(self):
        if self.client:
            await self.client.close()
