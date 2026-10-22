import asyncio
import time

import httpx
import pytest

from app.catalog import DisclosureCatalog
from app.errors import OpenDartError
from app.market_ranking import MarketRanking


def test_market_pages_units_cache_and_pinned_snapshot():
    async def check():
        calls = []
        multiplier = 1

        def handle(request):
            market = request.url.path.rsplit('/', 1)[-1]
            number = int(request.url.params['page'])
            calls.append((market, number))
            total = 101 if market == 'KOSPI' else 1
            start = (number - 1) * 100
            rows = [{'itemCode': f'{i + (1000 if market == "KOSDAQ" else 0):06}',
                     'marketValueRaw': str((i + 1) * multiplier)}
                    for i in range(start, min(start + 100, total))]
            if market == 'KOSDAQ':
                rows = [{'itemCode': '001000', 'marketValue': '1,234'}]
            return httpx.Response(200, json={
                'stockListCategoryType': market, 'page': number, 'pageSize': 100,
                'totalCount': total, 'stocks': rows,
            })

        ranking = MarketRanking(httpx.MockTransport(handle))
        first, duplicate = await asyncio.gather(ranking.get(), ranking.get())
        key, values = first
        assert duplicate == first
        assert len(calls) == 3 and len(values) == 102
        assert values['000100'] == 101
        assert values['001000'] == 1234 * 100_000_000
        ranking.loaded_at = time.monotonic() - 301
        multiplier = 2
        new_key, new_values = await ranking.get()
        assert new_key != key and new_values['000100'] == 202
        assert (await ranking.get(key))[1]['000100'] == 101
        assert len(calls) == 6
        with pytest.raises(OpenDartError, match='기업 정렬 기준이 만료'):
            await ranking.get('f' * 32)

    asyncio.run(check())


@pytest.mark.parametrize('failure', ['unavailable', 'incomplete', 'malformed'])
def test_never_returns_partial_or_random_ranking_on_provider_failure(failure):
    def handle(request):
        market = request.url.path.rsplit('/', 1)[-1]
        if failure == 'unavailable' and market == 'KOSDAQ':
            return httpx.Response(503)
        return httpx.Response(200, json={
            'stockListCategoryType': market, 'page': 1, 'pageSize': 100,
            'totalCount': 2 if failure == 'incomplete' else 1,
            'stocks': [{'itemCode': '005930', 'marketValueRaw': 'invalid' if failure == 'malformed' else '500'}],
        })

    async def check():
        ranking = MarketRanking(httpx.MockTransport(handle))
        with pytest.raises(OpenDartError) as error:
            await ranking.get()
        assert error.value.code == 'MARKET_RANKING_UNAVAILABLE'
        assert not ranking.snapshots

    asyncio.run(check())


def test_global_market_cap_sort_pagination_search_and_missing_values():
    async def check():
        catalog = DisclosureCatalog(None)
        catalog.companies = [
            {'corp_code': f'{i:08}', 'company_name': f'기업 {i:02}', 'stock_code': f'{i:06}'}
            for i in range(42)
        ]
        catalog.loaded_at = time.monotonic()
        key = 'a' * 32
        catalog.market_ranking.snapshots[key] = {f'{i:06}': i * 100 for i in range(1, 41)}
        catalog.market_ranking.loaded_at = time.monotonic()
        first = await catalog.search_companies('', sort='market_cap_desc')
        second = await catalog.search_companies('', offset=20, sort='market_cap_desc', snapshot=first['snapshot'])
        last = await catalog.search_companies('', offset=40, sort='market_cap_desc', snapshot=first['snapshot'])
        assert first['items'][0]['company_name'] == '기업 40'
        combined = first['items'] + second['items'] + last['items']
        assert len({row['corp_code'] for row in combined}) == 42
        assert [row['company_name'] for row in last['items']] == ['기업 00', '기업 41']
        assert first['has_more'] and not last['has_more']
        assert first['total_count'] == 42
        ascending = await catalog.search_companies('', sort='market_cap_asc')
        assert ascending['items'][0]['company_name'] == '기업 01'
        named = await catalog.search_companies('', sort='name')
        assert named['items'][0]['company_name'] == '기업 00'
        result = await catalog.search_companies('기업 0', sort='market_cap_desc')
        assert result['items'][0]['company_name'] == '기업 09'
        assert result['items'][-1]['company_name'] == '기업 00'
        code = await catalog.search_companies('000002', sort='market_cap_desc')
        assert [row['stock_code'] for row in code['items']] == ['000002']

    asyncio.run(check())
