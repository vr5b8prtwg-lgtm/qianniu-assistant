# -*- coding: utf-8 -*-
"""报价计算：闲鱼价 × 倍率 → 报价文案。"""
from __future__ import annotations

import math
from typing import Union

DEFAULT_TEMPLATE = "【{model}】报价 {price} 元，含运费另议"
DEFAULT_INQUIRY_TEMPLATE = "你好，{model}这款还有货吗，价格是多少"


def round_price(price: float, rounding: str = "round") -> float:
    """按配置取整：round | ceil | floor | none"""
    if rounding == "ceil":
        return float(math.ceil(price))
    if rounding == "floor":
        return float(math.floor(price))
    if rounding == "none":
        return round(price, 2)
    return float(round(price))


def calculate_quote(seller_price: Union[int, float], multiplier: float = 1.4,
                    rounding: str = "round") -> float:
    return round_price(float(seller_price) * float(multiplier), rounding)


def format_price(price: float) -> str:
    if float(price).is_integer():
        return str(int(price))
    return f"{price:.2f}"


def build_quote_message(model: str, quoted_price: float,
                        template: str = DEFAULT_TEMPLATE) -> str:
    return template.format(model=model, price=format_price(quoted_price))


def build_inquiry_message(model: str, template: str = DEFAULT_INQUIRY_TEMPLATE) -> str:
    """给闲鱼卖家的询价消息（半自动：只填不发送）。"""
    return template.format(model=model)


