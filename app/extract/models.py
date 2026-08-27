# -*- coding: utf-8 -*-
"""品牌正则库：覆盖常见工控品牌型号写法，供 extractor 使用。"""
from __future__ import annotations

import re

# 每个品牌对应一组正则；匹配时按顺序尝试，命中即归类为该品牌。
# 注意：正则中的 \\b 在原始字符串中写作 \\b 会匹配退格，必须用 r"\b"。
BRAND_PATTERNS = [
    (
        "西门子",
        [
            r"\b6(?:ES|SL|GK|AV|FC|DD|RA|EP|SN|AG|AD|GF|NH)\d{3,4}[A-Z0-9]*-[A-Z0-9-]{3,}\b",
            r"\b6[ESL][A-Z]\d{3,4}[A-Z0-9]*-[A-Z0-9-]{3,}\b",
        ],
    ),
    (
        "三菱",
        [
            r"\bFX[35]G?U?-\d{2,4}[A-Z]{1,4}(?:/[\w]+)?\b",
            r"\bMR-J[0-9A-Z]+-\d{2,4}[A-Z0-9]*\b",
            r"\bHC-[A-Z]{2}\d{2,4}[A-Z0-9-]*\b",
            r"\bHF-[A-Z]{2}\d{2,4}[A-Z0-9-]*\b",
            r"\bFR-[A-Z]\d{3,4}[-A-Z0-9]*\b",
            r"\bQ\d{2,3}[A-Z0-9]*CPU\b",
            r"\bQ[A-Z]{1,3}\d{2,3}[A-Z0-9-]{1,6}\b",
            r"\bL\d{2}[A-Z0-9]+\b",
        ],
    ),
    (
        "欧姆龙",
        [
            r"\bCP1[ELH]-[A-Z0-9-]+\b",
            r"\bC[JS][12]W-\w+\b",
            r"\bC[JS][12][A-Z0-9]{0,3}-CPU\w*\b",
            r"\bNX[A-Z0-9]+-\w+\b",
            r"\bNJ\d{3}-\w+\b",
            r"\bE5[CZDS]+[A-Z0-9]*-\w+\b",
            r"\bE[23][ZJK]-\w+\b",
        ],
    ),
    (
        "台达",
        [
            r"\bDVP-\d{2}[A-Z]{1,3}\d*\b",
            r"\bAS\d{2,3}[A-Z0-9-]{2,}\b",
            r"\bVFD[\w-]+\b",
            r"\bECMA-\w+\b",
            r"\bDOP-\w+\b",
        ],
    ),
    (
        "施耐德",
        [
            r"\bATV\d{2,3}[A-Z0-9]+\b",
            r"\bTM2\d{2}[A-Z0-9]+\b",
            r"\bBMX\w+\b",
            r"\b140[A-Z0-9]{4,}\b",
            r"\bSR[23]\w*-\w+\b",
        ],
    ),
    (
        "ABB",
        [
            r"\bACS\d{3}[-A-Z0-9]*\b",
            r"\b3G3[A-Z0-9-]{3,}\b",
        ],
    ),
    (
        "安川",
        [
            r"\bCIMR-\w+\b",
            r"\bSGD\w+-\w+\b",
            r"\bSGM\w+-\w+\b",
            r"\b[AVELJ]1000\b",
        ],
    ),
    (
        "基恩士",
        [
            r"\bKV-\w+\b",
            r"\bIL-\d{2,4}[A-Z0-9]*\b",
            r"\bLR-\w+\b",
            r"\bFS-\w+\b",
            r"\bIV\d?-\w+\b",
        ],
    ),
    (
        "松下",
        [
            r"\bM[A-Z]DHT\d{4}[A-Z0-9]*\b",
            r"\bFP-X\w*\b",
            r"\bCX-\d{3,4}\b",
        ],
    ),
    (
        "汇川",
        [
            r"\bIS\d{2,3}[A-Z0-9-]{2,}\b",
            r"\bMD\d{3,4}[A-Z0-9-]{2,}\b",
            r"\bAM\d{2,3}[A-Z0-9-]{2,}\b",
        ],
    ),
    (
        "信捷",
        [
            r"\bXC\d-\w+\b",
            r"\bXL\d-\w+\b",
            r"\bXD\d-\w+\b",
        ],
    ),
]

# 通用工控型号兜底：字母数字混合 + 连字符/斜杠结构，且需同时含字母和数字。
GENERIC_PATTERN = re.compile(r"\b[A-Z0-9]{2,9}[-/][A-Z0-9][A-Z0-9./-]{1,14}\b")

# 编译品牌正则
_BRAND_COMPILED = [(brand, [re.compile(p) for p in pats]) for brand, pats in BRAND_PATTERNS]

# 数字区（用于 OCR 纠错）
DIGITS = set("0123456789")

# OCR 易混字符映射（仅在 ocr=True 时使用）
OCR_CONFUSIONS = [
    ("O", "0"),
    ("o", "0"),
    ("I", "1"),
    ("l", "1"),
    ("S", "5"),
]


def iter_brand_patterns():
    yield from _BRAND_COMPILED


