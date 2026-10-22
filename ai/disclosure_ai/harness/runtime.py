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
    def __init__(self, task_id: str, ledger: Ledger, call_model=None):
        self.task_id = task_id
        self.ledger = ledger
        self.call_model = call_model
        self.inflight = {}
        self.client = None
        self.guard = None
        # 인코딩 파일도 실행 산출물 경로에 보관합니다.
        os.environ.setdefault(
            "TIKTOKEN_CACHE_DIR",
            str(Path(os.environ.get("XDG_CACHE_HOME", "outputs/cache")) / "tiktoken"),
        )
        self.encoding = tiktoken.get_encoding("o200k_base")

    def remaining(self, report: bool = False) -> float:
        reserve = 0 if report else 30
        return 120 - reserve - (time.time() - self.ledger.row(self.task_id)["started"])

    async def reserve(self, tokens: int, report: bool = False, role: str = "") -> None:
        async with self.ledger.lock:
            row = self.ledger.row(self.task_id)
            role_counts = json.loads(row["tools"])
            if role.startswith("perspective:") and role_counts.get("model:" + role, 0) >= 3:
                raise LimitReached("관점별 모델 호출 한도에 도달했습니다.")
            ceiling = 60000 if report else 48000
            turns = 8 if report else 7
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

    async def model(self, role: str, context: dict, schema, report: bool = False):
        prompts = Path(__file__).parents[1] / "prompts"
        system = (prompts / "common.md").read_text() + (prompts / f"{role}.md").read_text()
        if role == "base":
            kind = context.get("analysis_type", "UNKNOWN")
            if kind not in {"NEW", "CORRECTION", "UNKNOWN"}:
                kind = "UNKNOWN"
            system += (prompts / f"base_{kind.lower()}.md").read_text()
        input_limit, output_limit = (6000, 1500) if role == "perspective" else (10000, 2000)
        if role == "base":
            output_limit = 4000
        content = mask(json.dumps(context, ensure_ascii=False))
        schema_tokens = len(
            self.encoding.encode(json.dumps(schema.model_json_schema(), ensure_ascii=False))
        )
        available = input_limit - len(self.encoding.encode(system)) - schema_tokens - 100
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
                        if len(value) > 1:
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
                role + ":" + context.get("selection", {}).get("perspective_type", "")
                if role == "perspective"
                else role
            )
            await self.reserve(used_input + output_limit, report, role_scope)
            started = time.monotonic()
            try:
                async with asyncio.timeout(min(20, self.remaining(report) - (10 if report else 0))):
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
                self.ledger.event(
                    self.task_id,
                    "MODEL_END",
                    role=role,
                    tokens=actual,
                    elapsed=time.monotonic() - started,
                )
                return parsed
            except (ValidationError, ValueError, LengthFinishReasonError):
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

    async def review_output(
        self, payload: dict, *, grounding=False, corrections=(), advisory=False
    ) -> tuple[dict, list[str]]:
        return await review_output(
            self, payload, grounding=grounding, corrections=corrections, advisory=advisory
        )

    async def tool(self, name, args, invoke, *, report=False, scope=""):
        return await lookup.call(self, name, args, invoke, report=report, scope=scope)

    async def close(self):
        if self.client:
            await self.client.close()
