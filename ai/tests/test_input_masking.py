import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_analysis import ledger  # noqa: F401

from disclosure_ai.errors import LimitReached
from disclosure_ai.harness.output import masked_json
from disclosure_ai.harness.runtime import Harness
from disclosure_ai.schemas import BaseAnalysis, OutputReview


@pytest.mark.parametrize('separator', ['\n', '\r\n', '\t', '\\', '"'])
def test_masked_json_preserves_escapes_and_scalar_values(separator):
    context = {
        'memo': {'text': '연락처' + separator + 'researcher@example.com'},
        'sources': [{'quote': '문의\n010-1234-5678\n인증 sk-example123'}],
        'ratio': 0.010123456789,
        'amount': 1013700000000,
        'enabled': True,
        'missing': None,
    }
    original = copy.deepcopy(context)
    encoded = masked_json(context)
    decoded = json.loads(encoded)
    assert decoded['memo']['text'] == '연락처' + separator + '[이메일]'
    assert decoded['sources'][0]['quote'] == '문의\n[전화번호]\n인증 [인증정보]'
    for key in ['ratio', 'amount', 'enabled', 'missing']:
        assert decoded[key] == context[key]
        assert type(decoded[key]) is type(context[key])
    assert context == original
    assert 'example.com' not in encoded and '010-1234-5678' not in encoded


def test_long_report_reaches_model_with_valid_masked_and_bounded_json(ledger):  # noqa: F811
    context = {
        'analysis_type': 'CORRECTION',
        'memo': {'document_id': 'memo:fixture:v1',
                 'text': '공시 이전 메모\nresearcher@example.com\n' + '수주잔고 회복 검토입니다. ' * 6000},
        'context': [{'document_id': 'filing:current', 'location': 'line:1',
                     'quote': '계약 대상이 3척에서 2척으로 변경되었습니다.'}],
        'history_context': [{'document_id': 'filing:original', 'location': 'line:1',
                             'quote': '원계약은 3척입니다.'}],
        'ratio': 0.010123456789,
    }
    original = copy.deepcopy(context)
    parsed = BaseAnalysis(summary='분석 응답', proposals=[], selected=[],
                          no_additional_analysis_reason='추가 근거 확인 필요', limitations=[])
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))],
                               usage=SimpleNamespace(total_tokens=100))
    parse = AsyncMock(return_value=response)

    async def check():
        harness = Harness('task', ledger)
        harness.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))
        assert not harness.fits_model_input('base', context, BaseAnalysis)
        answer = await harness.model('base', context, BaseAnalysis)
        assert answer is parsed and parse.await_count == 1
        sent = parse.call_args.kwargs
        reduced = json.loads(sent['messages'][1]['content'])
        assert reduced['context_truncated'] is True
        assert reduced['memo']['document_id'] == context['memo']['document_id']
        assert reduced['context'][0] == context['context'][0]
        assert reduced['ratio'] == context['ratio']
        assert 'example.com' not in sent['messages'][1]['content']
        assert harness.fits_model_input('base', reduced, BaseAnalysis)
        assert len(harness.encoding.encode(sent['messages'][1]['content'])) <= harness.model_input_spec(
            'base', context, BaseAnalysis)[-1]
        assert sent['max_completion_tokens'] == 4000
        assert context == original
        assert ledger.row('task')['turns'] == 1

    asyncio.run(check())


def test_output_check_still_refuses_to_truncate_oversized_input(ledger):  # noqa: F811
    async def check():
        harness = Harness('task', ledger)
        parse = AsyncMock()
        harness.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))
        with pytest.raises(LimitReached, match='일부만 검사'):
            await harness.model('output_check', {'text': '\nresearcher@example.com\n' * 10000}, OutputReview)
        parse.assert_not_awaited()
        assert ledger.row('task')['turns'] == 0

    asyncio.run(check())
