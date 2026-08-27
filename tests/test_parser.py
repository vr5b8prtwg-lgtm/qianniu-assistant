# -*- coding: utf-8 -*-
"""闲鱼结果解析单元测试。"""
from pathlib import Path

from app.search.parser import parse_mtop_payload, parse_search_results

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_html_dom():
    html = (FIXTURES / "goofish_search_sample.html").read_text(encoding="utf-8")
    items = parse_search_results(html)
    assert len(items) == 2, f"应去重为 2 条，实际 {len(items)}"
    first = items[0]
    assert first.item_id == "10000000001"
    assert "6ES7214" in first.title
    assert first.price == "1234"
    assert first.seller == "卖家甲"
    assert first.url.startswith("https://www.goofish.com/item?id=")


def test_parse_mtop_json():
    raw = (FIXTURES / "goofish_search_sample.json").read_text(encoding="utf-8")
    items = parse_mtop_payload(raw)
    assert len(items) == 2
    by_id = {it.item_id: it for it in items}
    assert by_id["20000000001"].price == "145.0"
    assert by_id["20000000001"].seller == "卖家丁"
    assert by_id["20000000002"].price == "88.50"


def test_parse_empty():
    assert parse_search_results("") == []
    assert parse_mtop_payload("") == []
    assert parse_search_results("<html><body>无结果</body></html>") == []
