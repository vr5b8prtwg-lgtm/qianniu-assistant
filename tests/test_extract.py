# -*- coding: utf-8 -*-
"""型号提取单元测试。"""
import pytest

from app.extract.extractor import extract_models, normalize

# (文本, 期望型号片段)
SAMPLES = [
    ("6ES7214-1AG40-0XB0", "6ES7214-1AG40-0XB0"),
    ("6SL3210-1PE21-8UL0", "6SL3210-1PE21-8UL0"),
    ("6GK5204-2BC10-2AA3", "6GK5204-2BC10-2AA3"),
    ("6ES7315-2EH14-0AB0", "6ES7315-2EH14-0AB0"),
    ("FX3U-32MT/ES", "FX3U-32MT/ES"),
    ("FX5U-32MT/ESS", "FX5U-32MT/ESS"),
    ("MR-J4-40A", "MR-J4-40A"),
    ("Q02UCPU", "Q02UCPU"),
    ("FR-E740-1.5K", "FR-E740"),
    ("CP1E-N20DR-D", "CP1E-N20DR-D"),
    ("CP1L-EM40DT-D", "CP1L-EM40DT-D"),
    ("CJ2M-CPU31", "CJ2M-CPU31"),
    ("E5CC-QX2ASM-800", "E5CC-QX2ASM-800"),
    ("E3Z-D61", "E3Z-D61"),
    ("DVP-14SS2", "DVP-14SS2"),
    ("VFD-EL-W", "VFD-EL-W"),
    ("ECMA-C10604RS", "ECMA-C10604RS"),
    ("ATV312HU15N4", "ATV312HU15N4"),
    ("TM221CE16R", "TM221CE16R"),
    ("ACS510-01-031A-4", "ACS510-01-031A-4"),
    ("CIMR-AB4A0004", "CIMR-AB4A0004"),
    ("SGD7S-200A00A", "SGD7S-200A00A"),
    ("KV-7500", "KV-7500"),
    ("MADHT1505", "MADHT1505"),
    ("XC3-24T-E", "XC3-24T-E"),
]


@pytest.mark.parametrize("text,expected", SAMPLES)
def test_extract_basic(text, expected):
    models = extract_models(text)
    assert models, f"未提取到型号: {text}"
    found = any(
        m.model == expected or expected in m.model or m.model in expected
        for m in models
    )
    assert found, f"{text} -> {[m.model for m in models]}"


def test_extract_from_sentence():
    text = "老板这个有货吗？型号是6ES7214-1AG40-0XB0，多少钱？"
    models = extract_models(text)
    assert any(m.model == "6ES7214-1AG40-0XB0" for m in models)


def test_extract_multiple():
    text = "需要FX3U-32MT/ES和CP1E-N20DR-D各一台"
    models = extract_models(text)
    found = {m.model for m in models}
    assert "FX3U-32MT/ES" in found
    assert "CP1E-N20DR-D" in found


def test_no_false_positive():
    assert extract_models("你好，在吗") == []
    assert extract_models("价格100-200元") == []
    assert extract_models("2024-01-01发货") == []
    assert extract_models("https://www.example.com/abc") == []


def test_normalize_fullwidth_and_lower():
    assert normalize("6es7214-1ag40-0xb0") == "6ES7214-1AG40-0XB0"
    assert normalize("ｆｘ３ｕ－３２ＭＴ／ＥＳ") == "FX3U-32MT/ES"


def test_ocr_confusion():
    # O 被 OCR 识别成 0 的常见情况：0XB0 读成 OXBO
    text = "6ES7214-1AG40-OXBO"
    models = extract_models(text, ocr=True)
    assert models, "OCR 纠错后应能提取到型号"
    assert models[0].brand == "西门子"
