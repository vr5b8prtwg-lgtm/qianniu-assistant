# -*- coding: utf-8 -*-
"""一次性闲鱼扫码登录：打开浏览器让你扫码，验证登录态是否保持。"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config
from app.search.goofish import GoofishClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def main() -> int:
    cfg = load_config()
    client = GoofishClient(cfg)
    try:
        client.start()
        print("浏览器已打开闲鱼，请在浏览器里扫码登录（如果还没有登录）。")
        input("登录完成后按回车键继续验证...")
        ok = client.ensure_logged_in()
        if ok:
            print("[OK] 登录状态已保持，可以正常使用搜索功能。")
            return 0
        print("[FAIL] 未检测到登录状态，请重试。")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())

