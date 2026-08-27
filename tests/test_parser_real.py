# -*- coding: utf-8 -*-
"""闲鱼真实卡片结构解析测试（feeds-item-wrap 结构）。"""
from pathlib import Path

from app.search.parser import parse_search_results

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_real_feeds_structure():
    html = (FIXTURES / "goofish_feeds_real.html").read_text(encoding="utf-8")
    items = parse_search_results(html)
    assert len(items) == 2
    first = items[0]
    assert first.item_id == "30000000001"
    assert "Y2S3060-S" in first.title
    assert first.price == "55"
    assert first.seller == "江苏"
    assert "&amp;" not in first.url  # &amp; 应被还原为 &
    second = items[1]
    assert second.price == "1234.50"

