# -*- coding: utf-8 -*-
"""千牛工作台捕获：优先 Windows UI 自动化读文字，降级为窗口截图 + OCR。"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

log = logging.getLogger(__name__)

_CJK_OR_ALNUM = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# 千牛窗口内常见的浏览器/系统 UI 文本，不属于聊天内容
_JUNK_LINES = {
    "chrome legacy window", "应用程序", "navigation", "back", "forward",
    "reload", "address and search bar", "menu", "minimize", "maximize",
    "close", "restore", "page", "tab", "new tab", "settings", "search",
    "登录", "消息", "工作台", "宝贝管理", "交易管理", "店铺管理",
}


def _looks_like_chat_line(line: str) -> bool:
    s = line.strip()
    if len(s) < 2 or len(s) > 200:
        return False
    low = s.lower()
    if low in _JUNK_LINES:
        return False
    if _CJK_RE.search(s):
        return True
    # 无中文时：需像型号/链接/数字混合文本
    return bool(_CJK_OR_ALNUM.search(s)) and len(s) >= 5


@dataclass
class CaptureResult:
    messages: List[str] = field(default_factory=list)
    image_texts: List[str] = field(default_factory=list)
    method: str = "none"  # uia | ocr | not_running | error
    buyer_nick: str = ""
    note: str = ""


class QianniuCapture:
    def __init__(self, config: dict, ocr_engine=None):
        self.config = config or {}
        self.qcfg = self.config.get("qianniu", {})
        self.process_names = self.qcfg.get("process_names", ["AliWorkbench.exe"])
        self.max_messages = int(self.qcfg.get("max_messages", 20))
        self.ocr = ocr_engine

    # ---------- 进程 / 窗口 ----------
    def is_running(self) -> bool:
        try:
            import subprocess
            out = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            ).stdout
            for name in self.process_names:
                if name.lower() in out.lower():
                    return True
        except Exception as e:
            log.warning("检查千牛进程失败：%s", e)
        return False

    def _find_pids(self):
        try:
            import psutil
            return [
                p.info["pid"] for p in psutil.process_iter(["name", "pid"])
                if p.info["name"] in self.process_names
            ]
        except Exception:
            return []

    def _find_window(self):
        """通过 UI 自动化找千牛主窗口。"""
        import uiautomation as auto
        pids = self._find_pids()
        for pid in pids:
            try:
                win = auto.WindowControl(searchDepth=1, ProcessId=pid)
                if win.Exists(2, 0.5):
                    return win
            except Exception as e:
                log.debug("查找窗口失败 pid=%s: %s", pid, e)
        # 兜底：按进程名搜索
        for name in self.process_names:
            try:
                win = auto.WindowControl(searchDepth=1, ProcessName=name)
                if win.Exists(2, 0.5):
                    return win
            except Exception as e:
                log.debug("按进程名查找窗口失败 %s: %s", name, e)
        return None

    def _uia_text_lines(self) -> List[str]:
        """枚举窗口内文本控件，收集聊天文字。"""
        import uiautomation as auto
        win = self._find_window()
        if win is None:
            return []
        lines: List[str] = []

        def walk(ctrl, depth):
            if depth > 12:
                return
            try:
                for child in ctrl.GetChildren():
                    ctype = child.ControlTypeName or ""
                    name = (child.Name or "").strip()
                    if name and _looks_like_chat_line(name):
                        if "Text" in ctype or "Document" in ctype or "Edit" in ctype:
                            lines.append(name)
                        elif "Pane" in ctype and len(name) > 6:
                            lines.append(name)
                    walk(child, depth + 1)
            except Exception:
                return

        try:
            walk(win, 0)
        except Exception as e:
            log.warning("枚举千牛窗口控件失败：%s", e)
        # 去重保序
        seen, out = set(), []
        for ln in lines:
            if ln not in seen:
                seen.add(ln)
                out.append(ln)
        return out[-self.max_messages * 3:]

    # ---------- 截图 + OCR ----------
    def _screenshot_window(self, win=None) -> Optional[object]:
        """截取千牛主窗口（整屏裁剪），返回 PIL Image。"""
        from PIL import ImageGrab
        try:
            if win is not None:
                r = win.BoundingRectangle
                if r.left >= 0 and r.top >= 0 and r.right > r.left and r.bottom > r.top:
                    img = ImageGrab.grab()
                    w, h = img.size
                    left = max(0, min(r.left, w))
                    top = max(0, min(r.top, h))
                    right = max(left, min(r.right, w))
                    bottom = max(top, min(r.bottom, h))
                    return img.crop((left, top, right, bottom))
            return ImageGrab.grab()
        except Exception as e:
            log.warning("截屏失败：%s", e)
            return None

    def _ocr_lines(self, img) -> List[str]:
        if self.ocr is None or not getattr(self.ocr, "available", False):
            return []
        text = self.ocr.text(img)
        return [ln.strip() for ln in text.splitlines() if ln.strip()]

    def _image_ocr_texts(self, win) -> List[str]:
        """对窗口内图片控件逐个截图 OCR（用于客户发的产品图片）。"""
        import uiautomation as auto
        if self.ocr is None or not getattr(self.ocr, "available", False):
            return []
        texts = []
        try:
            def walk(ctrl, depth):
                if depth > 12:
                    return
                try:
                    for child in ctrl.GetChildren():
                        if child.ControlTypeName == auto.ControlType.ImageControl:
                            r = child.BoundingRectangle
                            if r.right > r.left and r.bottom > r.top and (r.right - r.left) > 60:
                                from PIL import ImageGrab
                                img = ImageGrab.grab()
                                w, h = img.size
                                left, top = max(0, r.left), max(0, r.top)
                                right, bottom = min(r.right, w), min(r.bottom, h)
                                if right > left and bottom > top:
                                    txt = self.ocr.text(img.crop((left, top, right, bottom)))
                                    if txt.strip():
                                        texts.append(txt.strip())
                        walk(child, depth + 1)
                except Exception:
                    return
            if win is not None:
                walk(win, 0)
        except Exception as e:
            log.warning("图片 OCR 失败：%s", e)
        return texts

    # ---------- 对外主入口 ----------
    def capture_current_conversation(self) -> CaptureResult:
        result = CaptureResult()
        if not self.is_running():
            result.method = "not_running"
            result.note = "未检测到千牛工作台进程"
            return result

        win = None
        try:
            win = self._find_window()
            if win is not None:
                result.buyer_nick = (win.Name or "").strip()
                lines = self._uia_text_lines()
                chat_lines = [ln for ln in lines if _looks_like_chat_line(ln)]
                if len(chat_lines) >= 3:
                    result.messages = chat_lines[-self.max_messages:]
                    result.method = "uia"
                    try:
                        result.image_texts = self._image_ocr_texts(win)
                    except Exception as e:
                        log.debug("图片 OCR 失败：%s", e)
                    result.note = "已通过窗口界面读取聊天内容"
                    return result
        except Exception as e:
            log.warning("UI 自动化读取失败：%s", e)

        # 降级：截图 + OCR
        img = self._screenshot_window(win)
        if img is not None:
            lines = self._ocr_lines(img)
            if lines:
                result.messages = lines[-self.max_messages:]
                result.method = "ocr"
                result.note = "已通过截图 OCR 读取聊天内容"
                return result
        result.method = "error"
        result.note = "未能读取聊天内容（千牛界面可能变化，或 OCR 不可用）"
        return result
