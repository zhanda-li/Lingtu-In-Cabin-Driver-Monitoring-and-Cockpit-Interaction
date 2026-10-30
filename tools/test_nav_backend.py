"""Navigation search contract tests using labelled test responses, no API calls."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ui'))
from amap import AMap


class SearchPlaces(unittest.IsolatedAsyncioTestCase):
    async def test_same_name_different_branches_are_preserved(self):
        client = AMap({'enabled': True, 'web_key': 'unit-test-placeholder'})
        client._rest = AsyncMock(return_value={'ok': True, 'data': {'tips': [
            {'name': '同名测试店', 'address': '测试街1号', 'location': '120.1,31.1'},
            {'name': '同名测试店', 'address': '测试街2号', 'location': '120.2,31.2'},
            {'name': '同名测试店', 'address': '重复记录', 'location': '120.1,31.1'},
        ]}})
        result = await client.search('测试店')
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['list']), 2)
        self.assertEqual([p['lng'] for p in result['list']], [120.1, 120.2])

    async def test_failed_search_is_not_a_place(self):
        client = AMap({'enabled': True, 'web_key': 'unit-test-placeholder'})
        client._rest = AsyncMock(return_value={'ok': False, 'why': 'test failure', 'data': {}})
        result = await client.search('测试')
        self.assertFalse(result['ok'])
        self.assertEqual(result['list'], [])


if __name__ == '__main__':
    unittest.main()
