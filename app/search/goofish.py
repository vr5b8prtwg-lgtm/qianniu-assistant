# -*- coding: utf-8 -*-
"""goofish.com 搜索客户端（半自动，人工处理验证码/询价）。"""
from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
from urllib.parse import quote

from app.search.parser import Listing, parse_mtop_payload, parse_search_results

log = logging.getLogger(__name__)


class GoofishError(Exception):
    pass


class CaptchaRequired(GoofishError):
    pass


@dataclass
class SearchOutcome:
    model: str
    listings: List[Listing] = field(default_factory=list)
    status: str = "ok"  # ok | empty | captcha | login_required | error
    note: str = ""
    url: str = ""


class GoofishClient:
    def __init__(self, config: dict):
        self.config = config or {}
        self.gcfg = self.config.get("goofish", {})
        self._pw = None
        self._ctx = None
        self._page = None
        self._last_search_at = 0.0

    # ---------- 生命周期 ----------
    def start(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        user_data = self.gcfg.get("user_data_dir") or str(Path("browser_profile").resolve())
        Path(user_data).mkdir(parents=True, exist_ok=True)
        configured = self.gcfg.get("browser_channel", "msedge")
        # 按优先级尝试：配置通道 -> msedge -> chromium（自动降级，避免安全软件拦截下载的浏览器）
        channels = [configured, "msedge", "chromium"]
        seen = set()
        last_err = None
        for channel in channels:
            if channel in seen:
                continue
            seen.add(channel)
            launch_kwargs = {
                "user_data_dir": user_data,
                "headless": bool(self.gcfg.get("headless", False)),
            }
            if channel and channel != "chromium":
                launch_kwargs["channel"] = channel
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(**launch_kwargs)
                break
            except Exception as e:
                last_err = e
                log.warning("浏览器通道 %s 启动失败：%s", channel, e)
        if self._ctx is None:
            self._pw.stop()
            raise GoofishError(
                "浏览器打开失败（可能被安全软件拦截）。请在 config.json 里把 "
                "goofish.browser_channel 改为 msedge 后重试；若仍失败请检查杀毒软件是否拦截浏览器。"
                f"详细信息：{last_err}"
            ) from last_err
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return self

    def close(self):
        try:
            if self._ctx:
                self._ctx.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._ctx = None
        self._page = None

    # ---------- 页面加载（容忍 SPA 二次跳转/超时，先看页面实际状态） ----------
    @staticmethod
    def _page_closed(e: Exception) -> bool:
        return "closed" in str(e).lower()

    def _goto_robust(self, url: str, settle_ms: int = 4000) -> str:
        """跳转并等待页面出现实际内容；返回页面 body 文本。即使 goto 抛异常，
        只要页面最终加载出内容就算成功（闲鱼搜索页常有客户端跳转导致 goto 报错）。
        若浏览器/页面已被关闭，立即抛出 GoofishError 以便上层自动重启。"""
        timeout = float(self.gcfg.get("search_timeout_ms", 45000))
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        except Exception as e:
            log.warning("goto 等待加载失败（继续检查页面状态）：%s", e)
            if self._page_closed(e):
                raise GoofishError("浏览器窗口已被关闭(closed)，正在自动重启…") from e
        deadline = time.time() + min(timeout / 1000.0, 30.0)
        while time.time() < deadline:
            try:
                if self._detect_captcha():
                    return self._safe_body_text()
                body = self._safe_body_text()
                if len(body) > 80:
                    if settle_ms:
                        self._page.wait_for_timeout(settle_ms)
                    return self._safe_body_text()
                self._page.wait_for_timeout(1200)
            except Exception as e:
                if self._page_closed(e):
                    raise GoofishError("浏览器窗口已被关闭(closed)，正在自动重启…") from e
                break
        return self._safe_body_text()

    # ---------- 登录 ----------
    def ensure_logged_in(self) -> bool:
        """访问闲鱼首页，返回是否已登录。"""
        if self._page is None:
            raise GoofishError("浏览器未启动")
        body = self._goto_robust("https://www.goofish.com/", settle_ms=2000)
        return not self._looks_not_logged_in(body)

    @staticmethod
    def _looks_not_logged_in(body: str) -> bool:
        """闲鱼未登录时的明确提示文案。"""
        return any(k in body for k in ("立即登录", "登录后可以更懂你", "扫码登录"))

    @staticmethod
    def _has_logged_in_marker(body: str) -> bool:
        # 导航里的“消息/发布/卖闲置”未登录时也显示，不能作为登录依据；
        # 仅当出现登录后才能看到的入口才视为已登录。
        markers = ["我的闲鱼", "退出登录", "账号设置", "我的订单"]
        return any(m in body for m in markers)

    def _safe_body_text(self) -> str:
        try:
            return self._page.inner_text("body") or ""
        except Exception:
            return ""

    # ---------- 搜索 ----------
    def _rate_limit(self):
        now = time.time()
        min_gap = float(self.gcfg.get("min_search_interval", 3.0))
        max_gap = float(self.gcfg.get("max_search_interval", 6.0))
        gap = now - self._last_search_at
        if gap < min_gap:
            time.sleep(min_gap - gap + random.uniform(0, max_gap - min_gap))
        self._last_search_at = time.time()

    def _detect_captcha(self) -> bool:
        try:
            url = self._page.url or ""
        except Exception:
            url = ""
        if any(k in url.lower() for k in ("captcha", "verify", "nc_")):
            return True
        body = self._safe_body_text()
        if any(k in body for k in ("拖动滑块", "请完成验证", "安全验证")):
            return True
        try:
            if self._page.locator("#nc_1_wrapper, .nc-container, .nc_wrapper").count() > 0:
                return True
        except Exception:
            pass
        return False

    def _try_mtop(self, keyword: str) -> List[Listing]:
        """尝试调用页面内部 mtop 接口拿结构化数据；失败返回空。"""
        api_names = self.gcfg.get("mtop_api_names") or []
        script = """
        (async () => {
            try {
                const lib = window.lib && window.lib.mtop;
                if (!lib || typeof lib.request !== 'function') return null;
                const apis = %s;
                const params = { q: %s };
                for (const api of apis) {
                    const res = await lib.request({ api, v: '1.0', type: 'GET', data: params, dataType: 'json' });
                    if (res && res.ret && String(res.ret[0]).indexOf('SUCCESS') >= 0) return JSON.stringify(res);
                }
                return null;
            } catch (e) { return null; }
        })()
        """ % (json.dumps(api_names), json.dumps(keyword))
        try:
            raw = self._page.evaluate(script)
        except Exception as e:
            log.debug("mtop 调用失败：%s", e)
            return []
        if not raw:
            return []
        return parse_mtop_payload(raw)

    def search(self, model: str) -> SearchOutcome:
        if self._page is None:
            raise GoofishError("浏览器未启动，请先启动")
        self._rate_limit()
        keyword = model.strip()
        url = f"https://www.goofish.com/search?q={quote(keyword)}"
        outcome = SearchOutcome(model=keyword, url=url)

        body = self._goto_robust(url)

        if self._detect_captcha():
            outcome.status = "captcha"
            outcome.note = "闲鱼要求完成安全验证，请在浏览器里手动处理滑块后点“继续”"
            return outcome

        # 1) mtop 结构化数据
        listings = self._try_mtop(keyword)
        # 2) 页面解析
        if not listings:
            try:
                html = self._page.content()
            except Exception:
                html = ""
            if html:
                listings = parse_search_results(html, self.gcfg.get("card_selectors"))
                self._dump_page(html, keyword)

        if listings:
            outcome.listings = listings
            outcome.status = "ok"
            outcome.note = f"找到 {len(listings)} 条结果"
            return outcome

        # 空结果或未登录
        if self._looks_not_logged_in(body):
            outcome.status = "login_required"
            outcome.note = "闲鱼未登录：请点面板「打开/登录闲鱼」在浏览器里扫码登录，登录后重新搜索"
        else:
            outcome.status = "empty"
            outcome.note = "没有解析到结果（页面结构可能变化，已保存页面快照到 page_dump/）"
        return outcome

    # ---------- 给卖家填询价消息（半自动：只填不发送） ----------
    CHAT_BUTTON_TEXTS = ("聊一聊", "我想要", "联系卖家", "留言", "联系")
    INPUT_SELECTORS = ("textarea", '[contenteditable="true"]', '[contenteditable="plaintext-only"]', '[role="textbox"]')

    def _find_chat_input(self, page):
        """在页面及所有 iframe 里找可见的聊天输入框。"""
        frames = [page]
        try:
            frames.extend(page.frames)
        except Exception:
            pass
        for f in frames:
            for sel in self.INPUT_SELECTORS:
                try:
                    loc = f.locator(sel)
                    n = loc.count()
                except Exception:
                    continue
                for j in range(min(n, 6)):
                    try:
                        el = loc.nth(j)
                        if el.is_visible():
                            return el
                    except Exception:
                        continue
        return None

    def _click_chat_button(self):
        """点击“聊一聊/我想要”等入口，返回可能新打开的聊天页面（无则 None）。"""
        pages_before = set()
        try:
            pages_before = set(self._ctx.pages)
        except Exception:
            pass
        for btn_text in self.CHAT_BUTTON_TEXTS:
            try:
                loc = self._page.get_by_text(btn_text, exact=False).first
                if loc.count() == 0:
                    continue
            except Exception:
                continue
            # 方式1：普通点击 + 监听弹窗
            try:
                with self._page.expect_popup(timeout=2000) as popup_info:
                    loc.click(timeout=3000)
                return popup_info.value
            except Exception:
                pass
            # 方式2：滚动到可见后强制点击（div 按钮常见）
            try:
                loc.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            try:
                loc.click(force=True, timeout=3000)
                break
            except Exception:
                try:
                    loc.evaluate("e => e.click()")
                    break
                except Exception:
                    continue
        # 检查是否新开了页面
        try:
            for p in self._ctx.pages:
                if p not in pages_before:
                    return p
        except Exception:
            pass
        return None

    def open_item_and_fill_message(self, url: str, message: str) -> dict:
        """打开商品页，打开与卖家的聊天并填入消息，绝不自动发送。
        返回 {"status": "filled"|"manual"|"error", "note": str, "url": str, "message": str}。"""
        result = {"status": "manual", "note": "", "url": url, "message": message}
        if self._page is None:
            result["note"] = "浏览器未启动"
            return result
        try:
            self._goto_robust(url, settle_ms=2500)
        except Exception as e:
            result["status"] = "error"
            result["note"] = f"打开商品页失败：{e}"
            return result

        chat_target = self._click_chat_button()
        try:
            self._page.wait_for_timeout(2500)
        except Exception:
            pass

        # 在聊天页 / 当前页（含 iframe）里找输入框，稍作轮询等待聊天加载
        candidates = []
        if chat_target is not None:
            candidates.append(chat_target)
        if self._page not in candidates:
            candidates.append(self._page)
        for _ in range(3):
            for p in candidates:
                input_loc = self._find_chat_input(p)
                if input_loc is not None:
                    try:
                        input_loc.click(timeout=3000)
                        p.wait_for_timeout(300)
                        p.keyboard.type(message, delay=15)
                        result["status"] = "filled"
                        result["note"] = "消息已填入（未发送），请在浏览器里按回车发送"
                        return result
                    except Exception as e:
                        result["note"] = f"输入框填写失败：{e}"
                        return result
            try:
                self._page.wait_for_timeout(1500)
            except Exception:
                break
        result["status"] = "manual"
        result["note"] = "未能自动定位聊天输入框：已打开商品页，请手动点「聊一聊」后粘贴消息发送"
        return result

    def _dump_page(self, html: str, keyword: str):
        try:
            dump_dir = Path("page_dump")
            dump_dir.mkdir(exist_ok=True)
            fname = dump_dir / f"goofish_{keyword[:20]}_{int(time.time())}.html"
            fname.write_text(html, encoding="utf-8", errors="ignore")
            log.info("页面快照已保存：%s", fname)
        except Exception:
            pass







