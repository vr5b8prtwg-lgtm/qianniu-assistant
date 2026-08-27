# -*- coding: utf-8 -*-
"""闲鱼搜索结果解析：DOM 解析 + 内嵌 JSON 提取。"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover
    BeautifulSoup = None


@dataclass
class Listing:
    item_id: str = ""
    title: str = ""
    price: str = ""
    seller: str = ""
    url: str = ""

    def as_dict(self) -> Dict[str, str]:
        return {"item_id": self.item_id, "title": self.title,
                "price": self.price, "seller": self.seller, "url": self.url}


DEFAULT_CARD_SELECTORS = [
    "a[class*='feeds-item-wrap']",
    "a[href*='/item?id=']",
    "div[class*='feeds-list'] a",
    "div[class*='item']",
    "div[class*='card']",
    "li[class*='item']",
]

_INIT_DATA_RE = re.compile(
    r"window\.__INIT[_A-Z]*DATA__\s*=\s*(\{.*?\})\s*;?\s*</script>", re.DOTALL
)
_NEXT_DATA_RE = re.compile(
    r"<script id=\"__NEXT_DATA__\"[^>]*>(.*?)</script>", re.DOTALL
)


def _clean_price(raw: str) -> str:
    if not raw:
        return ""
    # 去掉币种符号、空格和千分位逗号，再取数字（含小数）
    s = raw.replace("￥", "").replace("¥", "").replace(" ", "").replace(",", "")
    m = re.search(r"\d+(?:\.\d+)?", s)
    return m.group(0) if m else raw.strip()


def _clean_text(raw: str) -> str:
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw).strip()


def _node_text(node) -> str:
    if node is None:
        return ""
    return _clean_text(node.get_text(" ", strip=True))


def _walk_json(obj, out: List[Listing], seen: set) -> None:
    """递归找含 itemId + title 的对象。"""
    if isinstance(obj, dict):
        item_id = str(obj.get("itemId") or obj.get("item_id") or obj.get("itemid") or "")
        title = str(obj.get("title") or obj.get("subject") or "")
        if item_id.isdigit() and title and item_id not in seen:
            price = str(obj.get("price") or obj.get("reservePrice") or "")
            price_cent = obj.get("priceCent") or obj.get("price_cent")
            if price_cent and str(price_cent).replace(".", "", 1).isdigit():
                price = str(float(price_cent) / 100)
            seller = str(obj.get("sellerNick") or obj.get("seller") or obj.get("nick") or "")
            url = f"https://www.goofish.com/item?id={item_id}"
            seen.add(item_id)
            out.append(Listing(item_id=item_id, title=_clean_text(title),
                               price=_clean_price(str(price)), seller=_clean_text(seller), url=url))
        for v in obj.values():
            _walk_json(v, out, seen)
    elif isinstance(obj, list):
        for v in obj:
            _walk_json(v, out, seen)


def _parse_embedded_json(html: str) -> List[Listing]:
    out: List[Listing] = []
    seen: set = set()
    for pattern in (_INIT_DATA_RE, _NEXT_DATA_RE):
        m = pattern.search(html)
        if not m:
            continue
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        try:
            _walk_json(data, out, seen)
        except Exception as e:
            log.debug("解析内嵌 JSON 失败：%s", e)
        if out:
            break
    return out


def _parse_dom(html: str, card_selectors: List[str]) -> List[Listing]:
    if BeautifulSoup is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    # 优先：直接找指向商品详情页的链接（闲鱼商品卡片以 /item?id= 链接为特征）
    for a in soup.select('a[href*="/item?id="]'):
        cards.append(a)
    if not cards:
        for sel in card_selectors:
            cards = soup.select(sel)
            if cards:
                break
    out: List[Listing] = []
    seen: set = set()
    for card in cards:
        link = card if card.name == "a" else card.find("a", href=re.compile(r"/item\?id="))
        href = ""
        item_id = ""
        if link:
            href = link.get("href", "")
            if not href.startswith("http"):
                href = "https://www.goofish.com" + href
            m = re.search(r"id=(\d{5,20})", href)
            if m:
                item_id = m.group(1)
        # 标题：优先卡片内 row1 标题的 title 属性（完整标题），再取 main-title 文本
        title = ""
        row1 = card.select_one('[class*="row1-wrap-title"]')
        if row1:
            title = _clean_text(row1.get("title") or "") or _node_text(row1)
        if not title:
            title = _node_text(card.select_one(
                '[class*="main-title"], [class*="title"], [class*="name"], [class*="subject"]'))
        if not title:
            title = _node_text(card)
        if not title or not (item_id or href):
            continue
        key = item_id or f"{title}|{href}"
        if key in seen:
            continue
        seen.add(key)
        price_node = card.select_one('[class*="price"], [class*="money"], [class*="amount"]')
        price = _clean_price(_node_text(price_node))
        seller_node = card.select_one('[class*="seller"], [class*="user"], [class*="nick"], [class*="shop"]')
        seller = _clean_text(_node_text(seller_node))
        out.append(Listing(item_id=item_id, title=title, price=price, seller=seller, url=href))
    return out


def parse_mtop_payload(raw: str) -> List[Listing]:
    """解析 mtop 接口返回的 JSON 字符串。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return _parse_embedded_json(raw)
    out: List[Listing] = []
    _walk_json(data, out, set())
    return out


def parse_search_results(html: str, card_selectors: Optional[List[str]] = None) -> List[Listing]:
    """解析闲鱼搜索结果页 HTML，返回去重后的商品列表。"""
    if not html:
        return []
    listings = _parse_embedded_json(html)
    if not listings:
        listings = _parse_dom(html, card_selectors or DEFAULT_CARD_SELECTORS)
    # 去重
    seen: set = set()
    out: List[Listing] = []
    for it in listings:
        key = it.item_id or f"{it.title}|{it.price}"
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


