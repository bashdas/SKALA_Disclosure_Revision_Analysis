from openai import APIConnectionError, APIStatusError, LengthFinishReasonError

from disclosure_ai.config.settings import ModelSettings
from disclosure_ai.ports.model_gateway import ModelFormatError, ModelResponse, ModelTransportError
from disclosure_ai.runtime.retry import is_transient_status


class OpenAIModelAdapter:
    """Translate provider responses and errors into the internal model contract."""

    def __init__(self, client):
        self.client = client

    async def parse(self, messages, schema, output_limit):
        try:
            response = await self.client.chat.completions.parse(
                model=ModelSettings.from_environment().name,
                messages=messages,
                max_completion_tokens=output_limit,
                response_format=schema,
            )
        except LengthFinishReasonError as error:
            raise ModelFormatError("MODEL_OUTPUT_TRUNCATED") from error
        except APIConnectionError as error:
            raise ModelTransportError(True) from error
        except APIStatusError as error:
            raise ModelTransportError(is_transient_status(error.status_code)) from error
        return ModelResponse(
            parsed=response.choices[0].message.parsed,
            total_tokens=response.usage.total_tokens if response.usage else None,
        )

    async def close(self):
        await self.client.close()
