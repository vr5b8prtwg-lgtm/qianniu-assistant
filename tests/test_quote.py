# -*- coding: utf-8 -*-
"""报价计算单元测试。"""
from app.quote import build_quote_message, calculate_quote, format_price, round_price


def test_basic_multiply():
    assert calculate_quote(100, 1.4, "round") == 140.0


def test_rounding_modes():
    raw = 101.3 * 1.4  # 141.82
    assert round_price(raw, "round") == 142.0
    assert round_price(raw, "ceil") == 142.0
    assert round_price(raw, "floor") == 141.0
    assert round_price(raw, "none") == 141.82


def test_format_price():
    assert format_price(140.0) == "140"
    assert format_price(141.82) == "141.82"


def test_inquiry_message():
    from app.quote import build_inquiry_message
    msg = build_inquiry_message("Y2S3060-S")
    assert msg == "你好，Y2S3060-S这款还有货吗，价格是多少"
    custom = build_inquiry_message("6ES7214-1AG40-0XB0", "【{model}】还有货吗")
    assert custom == "【6ES7214-1AG40-0XB0】还有货吗"


def test_message_template():
    msg = build_quote_message("FX3U-32MT", 140)
    assert msg == "【FX3U-32MT】报价 140 元，含运费另议"
    msg2 = build_quote_message("6ES7214-1AG40-0XB0", 141.82, "报价：{model} -> {price}元")
    assert msg2 == "报价：6ES7214-1AG40-0XB0 -> 141.82元"


