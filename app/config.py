# -*- coding: utf-8 -*-
"""配置管理：读取 / 保存 config.json。"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("QIANNIU_ASSIST_CONFIG", APP_DIR / "config.json"))

DEFAULTS: Dict[str, Any] = {
    "quote": {
        "multiplier": 1.4,
        "rounding": "round",  # round | ceil | floor | none
        "template": "【{model}】报价 {price} 元，含运费另议",
    },
    "goofish": {
        "user_data_dir": str(APP_DIR / "browser_profile"),
        "headless": False,
        "browser_channel": "msedge",  # msedge | chromium
        "min_search_interval": 3.0,
        "max_search_interval": 6.0,
        "search_timeout_ms": 45000,
        # 备用：调用页面内部 mtop 接口的候选 api 名（若页面结构变化可在配置里更新）
        "mtop_api_names": [
            "mtop.taobao.idle.recmd.home.search",
        ],
        "card_selectors": [
            "div[class*='item']",
            "div[class*='card']",
            "li[class*='item']",
        ],
    },
    "inquiry": {
        "message_template": "你好，{model}这款还有货吗，价格是多少",
    },
    "ocr": {
        "engine": "rapidocr",  # rapidocr | disabled
    },
    "qianniu": {
        "process_names": ["AliWorkbench.exe"],
        "max_messages": 20,
    },
    "ui": {
        "always_on_top": True,
    },
    "auto_watch": False,
}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | os.PathLike | None = None) -> Dict[str, Any]:
    p = Path(path) if path else CONFIG_PATH
    data: Dict[str, Any] = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    cfg = deep_merge(DEFAULTS, data)
    # 写回合并后的默认值，方便用户看到全部可配置项
    try:
        save_config(cfg, p)
    except Exception:
        pass
    return cfg


def save_config(cfg: Dict[str, Any], path: str | os.PathLike | None = None) -> None:
    p = Path(path) if path else CONFIG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")





