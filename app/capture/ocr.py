# -*- coding: utf-8 -*-
"""OCR 封装：优先 rapidocr-onnxruntime，缺失时自动降级为 disabled。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

try:
    from rapidocr_onnxruntime import RapidOCR
    _RAPIDOCR_AVAILABLE = True
except Exception:  # pragma: no cover - 依赖未安装时的降级路径
    _RAPIDOCR_AVAILABLE = False


class OcrEngine:
    def __init__(self, engine: str = "rapidocr"):
        self.engine = engine
        self._rapid = None
        if engine != "disabled" and _RAPIDOCR_AVAILABLE:
            try:
                self._rapid = RapidOCR()
                log.info("RapidOCR 已就绪")
            except Exception as e:  # pragma: no cover
                log.warning("RapidOCR 初始化失败：%s", e)
                self._rapid = None

    @property
    def available(self) -> bool:
        return self._rapid is not None

    def recognize(self, image) -> List[Tuple[str, Optional[list], float]]:
        """识别图像，返回 [(text, box, confidence), ...]"""
        if self._rapid is None:
            return []
        try:
            result, _ = self._rapid(image)
        except Exception as e:  # pragma: no cover
            log.warning("OCR 识别失败：%s", e)
            return []
        out = []
        for item in result or []:
            if len(item) >= 3:
                out.append((str(item[1]), item[0], float(item[2])))
            elif len(item) >= 2:
                out.append((str(item[1]), None, 0.0))
        return out

    def text(self, image) -> str:
        parts = [t for t, _, _ in self.recognize(image)]
        return "\n".join(parts)

    def recognize_file(self, path: str | Path) -> str:
        if self._rapid is None:
            return ""
        try:
            return self.text(str(path))
        except Exception as e:  # pragma: no cover
            log.warning("OCR 读取文件失败 %s：%s", path, e)
            return ""
