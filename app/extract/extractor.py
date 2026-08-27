# -*- coding: utf-8 -*-
"""型号提取与归一化。"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import List

from app.extract.models import (
    DIGITS,
    GENERIC_PATTERN,
    OCR_CONFUSIONS,
    iter_brand_patterns,
)

_TOKEN_RE = re.compile(r"[A-Z0-9][A-Z0-9./-]{2,}")
_COMPACT_RE = re.compile(r"[\s.·・]")
_DATE_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$")
_NUMERIC_RANGE_RE = re.compile(r"^\d{1,4}[-/]\d{1,4}$")
_WEBSITE_RE = re.compile(r"^(https?://|www\.|[\w-]+\.(com|cn|net|org|io))", re.IGNORECASE)


@dataclass
class ExtractedModel:
    model: str
    brand: str = ""
    confidence: float = 0.0
    source: str = "text"  # text | ocr

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "brand": self.brand,
            "confidence": self.confidence,
            "source": self.source,
        }


def normalize(text: str, ocr: bool = False) -> str:
    """大写化、全角转半角。OCR 易混字符纠错在 extract_models 内按 token 做变体处理，
    避免把合法前缀（如 6ES 的 S）误改坏。"""
    return unicodedata.normalize("NFKC", text or "").upper()


def _is_plausible_model(token: str) -> bool:
    if not (3 <= len(token) <= 28):
        return False
    if _DATE_RE.match(token) or _NUMERIC_RANGE_RE.match(token):
        return False
    if _WEBSITE_RE.match(token):
        return False
    has_letter = any(ch.isalpha() for ch in token)
    has_digit = any(ch in DIGITS for ch in token)
    return has_letter and has_digit


def _match_brand(token: str) -> tuple:
    """返回 (brand, matched_regex) 或 (None, None)。"""
    for brand, patterns in iter_brand_patterns():
        for pat in patterns:
            m = pat.search(token)
            if m:
                return brand, m.group(0)
    return None, None


def _candidate_tokens(text_norm: str) -> List[str]:
    toks = set(_TOKEN_RE.findall(text_norm))
    # 紧凑形式（去空格/点）再提一遍，覆盖 "6ES7 214-1AG40-0XB0" 这类写法
    compact = _COMPACT_RE.sub("", text_norm)
    toks.update(_TOKEN_RE.findall(compact))
    out = []
    for t in toks:
        if not (3 <= len(t) <= 28):
            continue
        if _DATE_RE.match(t) or _NUMERIC_RANGE_RE.match(t) or _WEBSITE_RE.match(t):
            continue
        out.append(t)
    return out


def _ocr_variants(token: str) -> List[str]:
    """生成 OCR 易混字符纠错候选（O/0、I/l/1、S/5 双向替换），供兜底匹配。"""
    variants = [token]
    for src, dst in OCR_CONFUSIONS:
        for a, b in ((src, dst), (dst, src)):
            if a in token:
                v = token.replace(a, b)
                if v != token and v not in variants:
                    variants.append(v)
        if len(variants) >= 8:
            break
    return variants[:8]


def extract_models(text: str, ocr: bool = False) -> List[ExtractedModel]:
    """从文本中提取候选型号，按置信度降序返回。"""
    if not text or not text.strip():
        return []
    text_norm = normalize(text)
    tokens = _candidate_tokens(text_norm)
    results: List[ExtractedModel] = []
    seen = set()

    for token in tokens:
        # 1) 原 token 先走品牌正则（最可靠）
        brand, matched = _match_brand(token)
        if brand:
            model = matched or token
            if model in seen:
                continue
            seen.add(model)
            conf = 0.95 if not ocr else 0.9
            results.append(ExtractedModel(model=model, brand=brand, confidence=conf,
                                          source="ocr" if ocr else "text"))
            continue

        # 2) OCR 模式：易混字符纠错变体再试品牌正则
        if ocr:
            for v in _ocr_variants(token):
                brand2, matched2 = _match_brand(v)
                if brand2:
                    model = matched2 or v
                    if model in seen:
                        break
                    seen.add(model)
                    results.append(ExtractedModel(model=model, brand=brand2,
                                                  confidence=0.8, source="ocr"))
                    break

        # 3) 通用兜底：要求同时含字母和数字
        if not _is_plausible_model(token):
            continue
        m = GENERIC_PATTERN.search(token)
        if m:
            model = m.group(0)
            if model in seen:
                continue
            seen.add(model)
            conf = 0.7 if not ocr else 0.6
            results.append(ExtractedModel(model=model, brand="", confidence=conf,
                                          source="ocr" if ocr else "text"))

    results.sort(key=lambda r: r.confidence, reverse=True)
    return results
