import asyncio
import json
import time
from pathlib import Path

from pydantic import ValidationError

from disclosure_ai.analysis.reporting.grounding_review import mask
from disclosure_ai.errors import LimitReached
from disclosure_ai.ports.model_gateway import ModelFormatError, ModelGateway, ModelTransportError


class ModelExecutor:
    async def model(self, role: str, context: dict, schema, report: bool = False):
        prompts = Path(__file__).parents[1] / "llm" / "prompts"
        system = (prompts / "common.md").read_text() + (prompts / f"{role}.md").read_text()
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
                        if self.model_gateway is None:
                            from disclosure_ai.bootstrap import build_model_gateway

                            self.model_gateway = build_model_gateway(self.client)
                            self.client = getattr(self.model_gateway, "client", None)
                        gateway: ModelGateway = self.model_gateway
                        response = await gateway.parse(messages, schema, output_limit)
                        parsed = response.parsed
                        if parsed is None:
                            raise ValueError("모델이 구조화 응답을 반환하지 않았습니다.")
                        parsed = schema.model_validate(parsed)
                        actual = (
                            response.total_tokens
                            if response.total_tokens is not None
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
            except (ValidationError, ValueError, ModelFormatError):
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
            except (ModelTransportError, TimeoutError) as error:
                retryable = isinstance(error, TimeoutError) or error.retryable
                self.ledger.event(
                    self.task_id, "MODEL_ERROR", role=role, error=type(error).__name__
                )
                if not retryable or retries >= 2:
                    raise
                retries += 1
                await asyncio.sleep(min(0.2 * retries, max(0, self.remaining(report))))

    async def close(self):
        if self.model_gateway is not None:
            await self.model_gateway.close()
        elif self.client:
            await self.client.close()
