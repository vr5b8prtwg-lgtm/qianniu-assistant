# -*- coding: utf-8 -*-
"""冒烟检查：验证各模块可导入、核心功能可用（不依赖闲鱼登录）。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ok = True

    def check(name, fn):
        nonlocal ok
        try:
            fn()
            print(f"[OK] {name}")
        except Exception as e:
            ok = False
            print(f"[FAIL] {name}: {e!r}")

    def imports():
        import app.config
        import app.store
        import app.quote
        import app.extract.extractor
        import app.search.parser
        import app.search.goofish
        import app.capture.qianniu
        import app.capture.ocr
        import app.ui.panel

    def store_ops():
        from app.store import Store
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "t.db")
            cid = s.ensure_conversation("测试买家")
            s.add_message(cid, "in", "型号是6ES7214-1AG40-0XB0")
            s.add_model(cid, "6ES7214-1AG40-0XB0", "西门子", "text", 0.95)
            sid = s.add_search("6ES7214-1AG40-0XB0", "https://www.goofish.com/search?q=x", "ok", "")
            s.add_listings(sid, [{"item_id": "1", "title": "t", "price": "100", "seller": "s", "url": "u"}])
            s.add_quote("6ES7214-1AG40-0XB0", 100, 140, "【..】报价 140 元")
            assert s.get_cached_search("6ES7214-1AG40-0XB0") is not None
            assert len(s.recent_quotes()) == 1

    def quote_ops():
        from app.quote import calculate_quote, build_quote_message, build_inquiry_message
        assert calculate_quote(380, 1.4, "round") == 532.0
        assert "532" in build_quote_message("FX3U-32MT", 532)
        assert "还有货吗" in build_inquiry_message("Y2S3060-S")

    def extract_ops():
        from app.extract.extractor import extract_models
        assert any(m.model == "6ES7214-1AG40-0XB0" for m in extract_models("有货吗 6ES7214-1AG40-0XB0"))

    def parser_ops():
        from app.search.parser import parse_search_results
        from pathlib import Path as P
        f = P(__file__).parent.parent / "tests" / "fixtures" / "goofish_feeds_real.html"
        items = parse_search_results(f.read_text(encoding="utf-8"))
        assert len(items) == 2

    def ocr_available():
        from app.capture.ocr import OcrEngine
        eng = OcrEngine("rapidocr")
        print(f"    OCR 可用: {eng.available}")
        if not eng.available:
            raise RuntimeError("OCR 引擎不可用")

    def qianniu_check():
        from app.capture.qianniu import QianniuCapture
        from app.capture.ocr import OcrEngine
        cap = QianniuCapture({}, ocr_engine=OcrEngine("rapidocr"))
        running = cap.is_running()
        print(f"    千牛运行中: {running}")
        if not running:
            print("    (跳过捕获测试：未检测到千牛)")
            return
        res = cap.capture_current_conversation()
        print(f"    捕获方式: {res.method}, 消息数: {len(res.messages)}, 备注: {res.note}")

    def ui_import_offscreen():
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from app.ui.panel import MainPanel
        print("    UI 模块导入成功（offscreen）")

    check("模块导入", imports)
    check("SQLite 存储", store_ops)
    check("报价/询价", quote_ops)
    check("型号提取", extract_ops)
    check("结果解析", parser_ops)
    check("OCR 引擎", ocr_available)
    check("千牛捕获", qianniu_check)
    check("UI 导入", ui_import_offscreen)

    print()
    print("全部通过" if ok else "存在失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())


