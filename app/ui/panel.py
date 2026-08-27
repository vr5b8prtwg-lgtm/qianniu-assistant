# -*- coding: utf-8 -*-
"""常驻面板：捕获千牛 → 提取型号 → 闲鱼搜索 → 询价 → 报价。"""
from __future__ import annotations

import logging
import queue
import time
import webbrowser
from typing import Optional

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.capture.qianniu import QianniuCapture
from app.extract.extractor import extract_models
from app.quote import build_inquiry_message, build_quote_message, calculate_quote
from app.search.goofish import GoofishClient

log = logging.getLogger(__name__)

AUTO_WATCH_INTERVAL_MS = 8000


# ---------------------------------------------------------------- 捕获线程
class CaptureWorker(QThread):
    finished_ok = Signal(object)  # CaptureResult
    failed = Signal(str)

    def __init__(self, capturer: QianniuCapture, parent=None):
        super().__init__(parent)
        self.capturer = capturer

    def run(self):
        try:
            result = self.capturer.capture_current_conversation()
            self.finished_ok.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


# ---------------------------------------------------------------- 闲鱼线程
class GoofishThread(QThread):
    result = Signal(object)       # SearchOutcome
    fill_result = Signal(object)  # dict: open_item_and_fill_message 结果
    login_state = Signal(bool, str)
    error = Signal(str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self.q: "queue.Queue[tuple]" = queue.Queue()
        self._stop = False
        self.client: Optional[GoofishClient] = None

    def stop(self):
        self._stop = True
        try:
            self.q.put(("__stop__", None))
        except Exception:
            pass

    def submit(self, action: str, payload=None):
        self.q.put((action, payload))

    @staticmethod
    def _is_closed_error(e: Exception) -> bool:
        msg = str(e).lower()
        return "closed" in msg or "target page" in msg or "已被关闭" in msg

    def _start_client(self) -> bool:
        try:
            self.client = GoofishClient(self.config)
            self.client.start()
            return True
        except Exception as e:
            self.error.emit(f"启动浏览器失败：{e}")
            self.client = None
            return False

    def _run_action(self, action, payload):
        if action == "ensure_login":
            ok = self.client.ensure_logged_in()
            self.login_state.emit(ok, "已登录闲鱼" if ok else "未登录，请在浏览器里扫码登录")
        elif action == "search":
            outcome = self.client.search(payload)
            self.result.emit(outcome)
        elif action == "fill_message":
            res = self.client.open_item_and_fill_message(payload["url"], payload["message"])
            self.fill_result.emit(res)

    def run(self):
        while not self._stop:
            try:
                action, payload = self.q.get(timeout=1.0)
            except queue.Empty:
                continue
            if action == "__stop__":
                break
            if self.client is None and not self._start_client():
                continue
            try:
                self._run_action(action, payload)
            except Exception as e:
                if self._is_closed_error(e):
                    self.error.emit("浏览器窗口被关闭，正在自动重启浏览器并重试…")
                    log.warning("浏览器关闭，重启后重试：%s", e)
                    try:
                        if self.client:
                            self.client.close()
                    except Exception:
                        pass
                    self.client = None
                    if self._start_client():
                        try:
                            self._run_action(action, payload)
                        except Exception as e2:
                            self.error.emit(f"重试失败：{e2}")
                    continue
                self.error.emit(f"{'检查登录' if action == 'ensure_login' else '搜索'}失败：{e}")
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass


# ---------------------------------------------------------------- 主面板
class MainPanel(QMainWindow):
    def __init__(self, config: dict, store=None):
        super().__init__()
        self.config = config
        self.store = store
        self.capturer = QianniuCapture(config, ocr_engine=None)
        self._lazy_ocr()
        self.capture_worker: Optional[CaptureWorker] = None
        self.current_model: str = ""
        self.last_result_items: list = []

        self._build_ui()
        self._wire_signals()
        self._apply_config_to_ui()
        self._init_goofish_thread()

        self.statusBar().showMessage("就绪：点“捕获当前会话”读取千牛聊天，或直接输入型号")

    # ---------------- UI 构建 ----------------
    def _build_ui(self):
        self.setWindowTitle("千牛工作台助手 - 捕获型号 + 闲鱼搜索 + 报价")
        self.resize(880, 660)
        tabs = QTabWidget()
        tabs.addTab(self._build_work_tab(), "工作台")
        tabs.addTab(self._build_history_tab(), "历史")
        tabs.addTab(self._build_settings_tab(), "设置")
        self.setCentralWidget(tabs)

    def _build_work_tab(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)

        # ① 捕获千牛会话
        cap_box = QGroupBox("① 捕获千牛会话")
        cap_layout = QVBoxLayout(cap_box)
        row = QHBoxLayout()
        self.btn_capture = QPushButton("捕获当前会话 (F8)")
        self.btn_capture.setMinimumHeight(34)
        self.chk_autowatch = QCheckBox("自动监听新消息")
        row.addWidget(self.btn_capture)
        row.addWidget(self.chk_autowatch)
        row.addStretch(1)
        cap_layout.addLayout(row)
        self.lbl_capture = QLabel("未捕获（需打开千牛工作台并点开客户会话）")
        self.lbl_capture.setWordWrap(True)
        cap_layout.addWidget(self.lbl_capture)
        root.addWidget(cap_box)

        # ② 型号
        model_box = QGroupBox("② 型号（从聊天/图片提取，或手动输入）")
        model_layout = QVBoxLayout(model_box)
        row2 = QHBoxLayout()
        self.edt_model = QLineEdit()
        self.edt_model.setPlaceholderText("当前型号，可手动修改或从候选中选择")
        self.cmb_candidates = QComboBox()
        self.cmb_candidates.setMinimumWidth(240)
        self.btn_pick = QPushButton("设为当前型号")
        self.btn_clipboard = QPushButton("从剪贴板提取")
        self.btn_clipboard.setToolTip("读取剪贴板里的文字，自动识别其中的型号并填入")
        row2.addWidget(self.edt_model, 3)
        row2.addWidget(self.cmb_candidates, 2)
        row2.addWidget(self.btn_pick)
        row2.addWidget(self.btn_clipboard)
        model_layout.addLayout(row2)
        root.addWidget(model_box)

        # ③ 闲鱼
        xf_box = QGroupBox("③ 闲鱼搜索")
        xf_layout = QVBoxLayout(xf_box)
        row3 = QHBoxLayout()
        self.btn_login = QPushButton("打开/登录闲鱼")
        self.btn_search = QPushButton("在闲鱼搜索当前型号")
        self.btn_search.setMinimumHeight(32)
        row3.addWidget(self.btn_login)
        row3.addWidget(self.btn_search)
        row3.addStretch(1)
        xf_layout.addLayout(row3)
        self.lbl_search = QLabel("尚未搜索")
        self.lbl_search.setWordWrap(True)
        xf_layout.addWidget(self.lbl_search)
        self.tbl_results = QTableWidget(0, 4)
        self.tbl_results.setHorizontalHeaderLabels(["标题", "价格", "卖家", "链接"])
        self.tbl_results.horizontalHeader().setStretchLastSection(True)
        self.tbl_results.setColumnWidth(0, 380)
        self.tbl_results.setColumnWidth(1, 80)
        self.tbl_results.setColumnWidth(2, 120)
        self.tbl_results.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_results.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        xf_layout.addWidget(self.tbl_results)
        row4 = QHBoxLayout()
        self.btn_copy_link = QPushButton("复制选中链接")
        self.btn_open = QPushButton("用浏览器打开选中项")
        self.btn_inquiry = QPushButton("自动填询价消息(不发送)")
        self.btn_inquiry.setToolTip("把“你好，型号这款还有货吗，价格是多少”自动填入与卖家的聊天框，发送仍由你手动按回车，降低风控风险")
        row4.addWidget(self.btn_copy_link)
        row4.addWidget(self.btn_open)
        row4.addWidget(self.btn_inquiry)
        row4.addStretch(1)
        xf_layout.addLayout(row4)
        root.addWidget(xf_box, 3)

        # ④ 报价
        q_box = QGroupBox("④ 报价（闲鱼成交价 × 倍率）")
        q_layout = QFormLayout(q_box)
        self.edt_price = QLineEdit()
        self.edt_price.setPlaceholderText("例如 380")
        self.btn_quote = QPushButton("生成报价")
        price_row = QHBoxLayout()
        price_row.addWidget(self.edt_price)
        price_row.addWidget(self.btn_quote)
        q_layout.addRow("卖家成交价(元)", price_row)
        self.lbl_quote = QLabel("输入成交价后点“生成报价”")
        self.lbl_quote.setWordWrap(True)
        q_layout.addRow("报价文案", self.lbl_quote)
        row5 = QHBoxLayout()
        self.btn_copy_quote = QPushButton("复制报价")
        row5.addWidget(self.btn_copy_quote)
        row5.addStretch(1)
        q_layout.addRow("", row5)
        root.addWidget(q_box)

        return w

    def _build_history_tab(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.addWidget(QLabel("最近搜索"))
        self.tbl_searches = QTableWidget(0, 4)
        self.tbl_searches.setHorizontalHeaderLabels(["型号", "结果数", "状态", "时间"])
        root.addWidget(self.tbl_searches)
        root.addWidget(QLabel("最近报价"))
        self.tbl_quotes = QTableWidget(0, 4)
        self.tbl_quotes.setHorizontalHeaderLabels(["型号", "成交价", "报价", "时间"])
        root.addWidget(self.tbl_quotes)
        return w

    def _build_settings_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.spin_multiplier = QDoubleSpinBox()
        self.spin_multiplier.setRange(1.0, 10.0)
        self.spin_multiplier.setSingleStep(0.1)
        self.spin_multiplier.setDecimals(2)
        self.cmb_rounding = QComboBox()
        self.cmb_rounding.addItems(["round", "ceil", "floor", "none"])
        self.edt_template = QLineEdit()
        self.edt_inquiry_template = QLineEdit()
        self.spin_min_interval = QDoubleSpinBox()
        self.spin_min_interval.setRange(0, 30)
        self.spin_min_interval.setDecimals(1)
        self.spin_max_interval = QDoubleSpinBox()
        self.spin_max_interval.setRange(0, 60)
        self.spin_max_interval.setDecimals(1)
        self.chk_topmost = QCheckBox("窗口置顶")
        form.addRow("报价倍率", self.spin_multiplier)
        form.addRow("取整方式", self.cmb_rounding)
        form.addRow("报价模板", self.edt_template)
        form.addRow("询价消息模板", self.edt_inquiry_template)
        form.addRow("搜索最小间隔(秒)", self.spin_min_interval)
        form.addRow("搜索最大间隔(秒)", self.spin_max_interval)
        form.addRow("", self.chk_topmost)
        self.btn_save_settings = QPushButton("保存设置")
        form.addRow("", self.btn_save_settings)
        return w

    # ---------------- 信号 ----------------
    def _wire_signals(self):
        self.btn_capture.clicked.connect(self.on_capture)
        self.chk_autowatch.toggled.connect(self.on_autowatch_toggled)
        self.cmb_candidates.currentTextChanged.connect(self.on_candidate_changed)
        self.btn_pick.clicked.connect(self.on_pick_candidate)
        self.btn_clipboard.clicked.connect(self.on_clipboard_extract)
        self.btn_login.clicked.connect(self.on_login)
        self.btn_search.clicked.connect(self.on_search)
        self.btn_copy_link.clicked.connect(self.on_copy_link)
        self.btn_open.clicked.connect(self.on_open_item)
        self.btn_inquiry.clicked.connect(self.on_fill_inquiry)
        self.btn_quote.clicked.connect(self.on_quote)
        self.btn_copy_quote.clicked.connect(self.on_copy_quote)
        self.btn_save_settings.clicked.connect(self.on_save_settings)

        # F8 快捷键
        from PySide6.QtGui import QShortcut, QKeySequence
        self._shortcut = QShortcut(QKeySequence("F8"), self)
        self._shortcut.activated.connect(self.on_capture)

    def _apply_config_to_ui(self):
        q = self.config.get("quote", {})
        self.spin_multiplier.setValue(float(q.get("multiplier", 1.4)))
        idx = ["round", "ceil", "floor", "none"].index(q.get("rounding", "round"))
        self.cmb_rounding.setCurrentIndex(idx)
        self.edt_template.setText(q.get("template", "【{model}】报价 {price} 元，含运费另议"))
        self.edt_inquiry_template.setText(
            self.config.get("inquiry", {}).get("message_template", "你好，{model}这款还有货吗，价格是多少"))
        g = self.config.get("goofish", {})
        self.spin_min_interval.setValue(float(g.get("min_search_interval", 3.0)))
        self.spin_max_interval.setValue(float(g.get("max_search_interval", 6.0)))
        self.chk_topmost.setChecked(bool(self.config.get("ui", {}).get("always_on_top", True)))
        self.chk_autowatch.setChecked(bool(self.config.get("auto_watch", False)))
        self._apply_topmost()

    def _apply_topmost(self):
        flag = Qt.WindowType.WindowStaysOnTopHint if self.chk_topmost.isChecked() else Qt.WindowType.Widget
        self.setWindowFlag(flag, True)
        self.show()

    # ---------------- OCR 惰性注入 ----------------
    def _lazy_ocr(self):
        try:
            from app.capture.ocr import OcrEngine
            engine = self.config.get("ocr", {}).get("engine", "rapidocr")
            ocr = OcrEngine(engine)
            self.capturer.ocr = ocr
            if not ocr.available:
                log.warning("OCR 不可用，图片咨询将无法自动识别")
        except Exception as e:
            log.warning("OCR 初始化失败：%s", e)

    # ---------------- 闲鱼线程 ----------------
    def _init_goofish_thread(self):
        self.gf_thread = GoofishThread(self.config)
        self.gf_thread.result.connect(self.on_search_result)
        self.gf_thread.fill_result.connect(self.on_fill_result)
        self.gf_thread.login_state.connect(self.on_login_state)
        self.gf_thread.error.connect(lambda msg: self._show_status(f"闲鱼错误：{msg}"))
        self.gf_thread.start()

    def closeEvent(self, event):
        try:
            if self.gf_thread:
                self.gf_thread.stop()
                self.gf_thread.wait(3000)
        except Exception:
            pass
        super().closeEvent(event)

    # ---------------- 捕获 ----------------
    def on_capture(self):
        if self.capture_worker and self.capture_worker.isRunning():
            return
        self.lbl_capture.setText("正在读取千牛会话…")
        self.capture_worker = CaptureWorker(self.capturer)
        self.capture_worker.finished_ok.connect(self.on_capture_result)
        self.capture_worker.failed.connect(
            lambda e: self.lbl_capture.setText(f"捕获失败：{e}"))
        self.capture_worker.start()

    def on_capture_result(self, result):
        if result.method == "not_running":
            self.lbl_capture.setText("未检测到千牛工作台进程，请先打开千牛")
            return
        if result.method == "error":
            self.lbl_capture.setText(f"读取失败：{result.note}")
            return
        buyer = result.buyer_nick or "当前会话"
        self.lbl_capture.setText(
            f"买家：{buyer}　方式：{'窗口读取' if result.method == 'uia' else '截图OCR'}　"
            f"消息 {len(result.messages)} 条 / 图片 {len(result.image_texts)} 张\n{result.note}")
        texts = list(result.messages) + list(result.image_texts)
        combined = "\n".join(texts)
        models = extract_models(combined, ocr=(result.method == "ocr"))
        self._set_candidates(models)
        if self.store:
            cid = self.store.ensure_conversation(buyer_nick=buyer)
            for t in texts:
                self.store.add_message(cid, "in", t)
            for m in models[:5]:
                self.store.add_model(cid, m.model, m.brand, m.source, m.confidence)
        if not models:
            self.lbl_capture.setText(self.lbl_capture.text() + "\n未识别到型号，请检查聊天内容或手动输入")

    def _set_candidates(self, models):
        self.cmb_candidates.clear()
        if models:
            for m in models[:10]:
                label = f"{m.model}（{m.brand or '通用'} {m.confidence:.2f}）"
                self.cmb_candidates.addItem(label, m.model)
            self.cmb_candidates.setCurrentIndex(0)
            self.on_candidate_changed(self.cmb_candidates.currentText())
        else:
            self.edt_model.setText("")

    def on_candidate_changed(self, text):
        if self.cmb_candidates.currentData():
            self.edt_model.setText(self.cmb_candidates.currentData())

    def on_pick_candidate(self):
        model = self.edt_model.text().strip()
        if model:
            self.current_model = model
            self._show_status(f"当前型号：{model}")
        else:
            QMessageBox.information(self, "提示", "请先输入或选择型号")

    def on_autowatch_toggled(self, checked):
        self.config["auto_watch"] = checked
        if checked and not hasattr(self, "_watch_timer"):
            self._watch_timer = QTimer(self)
            self._watch_timer.timeout.connect(self.on_capture)
        if checked:
            self._watch_timer.start(AUTO_WATCH_INTERVAL_MS)
        else:
            self._watch_timer.stop()

    # ---------------- 型号输入 ----------------
    def on_clipboard_extract(self):
        text = QApplication.clipboard().text() or ""
        models = extract_models(text)
        if models:
            self._set_candidates(models)
            self._show_status(f"已从剪贴板提取型号：{models[0].model}")
        else:
            QMessageBox.information(self, "提示", "剪贴板里没有识别到型号，请手动输入")

    def _ensure_model(self) -> bool:
        self.current_model = self.edt_model.text().strip()
        if not self.current_model:
            QMessageBox.information(self, "提示", "请先输入型号")
            return False
        return True

    # ---------------- 闲鱼 ----------------
    def on_login(self):
        self._show_status("正在打开闲鱼浏览器（首次请扫码登录）…")
        self.gf_thread.submit("ensure_login")

    def on_login_state(self, ok, note):
        self.lbl_search.setText(note)
        self._show_status(note)

    def on_search(self):
        if not self._ensure_model():
            return
        self.lbl_search.setText(f"正在闲鱼搜索：{self.current_model} …")
        self._show_status(f"正在搜索 {self.current_model}")
        self.gf_thread.submit("search", self.current_model)

    def on_search_result(self, outcome):
        if self.store:
            search_id = self.store.add_search(outcome.model, outcome.url, outcome.status, outcome.note)
            if outcome.listings:
                self.store.add_listings(search_id, [l.as_dict() for l in outcome.listings])
        if outcome.status == "captcha":
            self.lbl_search.setText(
                "闲鱼要求安全验证：请在浏览器中手动拖动滑块完成验证，完成后点“在闲鱼搜索当前型号”重试。")
            self._show_status("需要人工过验证码")
            QMessageBox.information(self, "需要人工验证",
                                    "闲鱼弹出了验证码，请在浏览器窗口里手动完成滑块验证，然后重新点搜索。")
            return
        if outcome.status == "login_required":
            self.lbl_search.setText(outcome.note)
            self._show_status("闲鱼未登录，请扫码")
            QMessageBox.information(self, "需要登录闲鱼",
                                    "闲鱼当前未登录，无法搜索到商品。\n\n请点「打开/登录闲鱼」按钮，在浏览器里用淘宝/支付宝扫码登录一次，然后再点搜索。")
            return
        if outcome.status == "error":
            self.lbl_search.setText(f"搜索失败：{outcome.note}")
            self._show_status("搜索失败")
            return
        if outcome.status == "empty":
            self.lbl_search.setText(outcome.note)
            self._show_status("无结果")
            return
        self.last_result_items = [l.as_dict() for l in outcome.listings]
        self.tbl_results.setRowCount(0)
        for it in self.last_result_items:
            r = self.tbl_results.rowCount()
            self.tbl_results.insertRow(r)
            self.tbl_results.setItem(r, 0, QTableWidgetItem(it.get("title", "")))
            self.tbl_results.setItem(r, 1, QTableWidgetItem(it.get("price", "")))
            self.tbl_results.setItem(r, 2, QTableWidgetItem(it.get("seller", "")))
            self.tbl_results.setItem(r, 3, QTableWidgetItem(it.get("url", "")))
        self.lbl_search.setText(outcome.note)
        self._show_status(outcome.note)
        self._refresh_history()

    def _selected_row_url(self) -> str:
        row = self.tbl_results.currentRow()
        if row < 0:
            return ""
        return self.tbl_results.item(row, 3).text() if self.tbl_results.item(row, 3) else ""

    def on_copy_link(self):
        url = self._selected_row_url()
        if url:
            QApplication.clipboard().setText(url)
            self._show_status("链接已复制")
        else:
            QMessageBox.information(self, "提示", "请先选中一行结果")

    def on_open_item(self):
        url = self._selected_row_url()
        if url:
            webbrowser.open(url)
        else:
            QMessageBox.information(self, "提示", "请先选中一行结果")

    # ---------------- 给卖家填询价消息（半自动） ----------------
    def on_fill_inquiry(self):
        if not self._ensure_model():
            return
        url = self._selected_row_url()
        if not url and self.last_result_items:
            url = self.last_result_items[0].get("url", "")
        if not url:
            QMessageBox.information(self, "提示", "请先在闲鱼搜索出结果，并选中一行商品")
            return
        template = self.config.get("inquiry", {}).get(
            "message_template", "你好，{model}这款还有货吗，价格是多少")
        try:
            message = build_inquiry_message(self.current_model, template)
        except Exception:
            message = f"你好，{self.current_model}这款还有货吗，价格是多少"
        self.lbl_search.setText(f"正在打开商品页并填写询价消息（不会自动发送）…")
        self._show_status("半自动填消息：请稍候")
        self.gf_thread.submit("fill_message", {"url": url, "message": message})

    def on_fill_result(self, res: dict):
        status = res.get("status", "manual")
        note = res.get("note", "")
        message = res.get("message", "")
        if status == "filled":
            self.lbl_search.setText(note)
            self._show_status("已填入消息（未发送），请在浏览器里按回车发送")
        elif status == "error":
            self.lbl_search.setText(f"填写失败：{note}")
            self._show_status("填写失败")
        else:
            if message:
                QApplication.clipboard().setText(message)
            self.lbl_search.setText(note + "（消息已复制到剪贴板，可直接粘贴）")
            self._show_status("已复制询价消息到剪贴板")
            QMessageBox.information(
                self, "请手动发送",
                f"{note}\n\n询价消息已复制到剪贴板，请在浏览器商品页里粘贴到聊天框后手动发送。")

    # ---------------- 报价 ----------------
    def on_quote(self):
        if not self._ensure_model():
            return
        try:
            price = float(self.edt_price.text().strip().replace(",", ""))
        except ValueError:
            QMessageBox.information(self, "提示", "请输入有效的卖家成交价数字")
            return
        q = self.config.get("quote", {})
        quoted = calculate_quote(price, q.get("multiplier", 1.4), q.get("rounding", "round"))
        msg = build_quote_message(self.current_model, quoted, q.get(
            "template", "【{model}】报价 {price} 元，含运费另议"))
        self.lbl_quote.setText(msg)
        if self.store:
            self.store.add_quote(self.current_model, price, quoted, msg)
        self._show_status(f"报价已生成：{msg}")
        self._refresh_history()

    def on_copy_quote(self):
        text = self.lbl_quote.text()
        if text and "输入成交价后" not in text:
            QApplication.clipboard().setText(text)
            self._show_status("报价文案已复制，可粘贴到千牛发送")
        else:
            QMessageBox.information(self, "提示", "请先生成报价")

    # ---------------- 设置 ----------------
    def on_save_settings(self):
        q = self.config.setdefault("quote", {})
        q["multiplier"] = float(self.spin_multiplier.value())
        q["rounding"] = self.cmb_rounding.currentText()
        q["template"] = self.edt_template.text()
        self.config.setdefault("inquiry", {})["message_template"] = self.edt_inquiry_template.text()
        g = self.config.setdefault("goofish", {})
        g["min_search_interval"] = float(self.spin_min_interval.value())
        g["max_search_interval"] = float(self.spin_max_interval.value())
        self.config.setdefault("ui", {})["always_on_top"] = bool(self.chk_topmost.isChecked())
        from app.config import save_config
        save_config(self.config)
        self._apply_topmost()
        self._show_status("设置已保存（下次搜索生效）")

    # ---------------- 历史 ----------------
    def _refresh_history(self):
        if not self.store:
            return
        searches = self.store.recent_searches(30)
        self.tbl_searches.setRowCount(0)
        for row in searches:
            r = self.tbl_searches.rowCount()
            self.tbl_searches.insertRow(r)
            self.tbl_searches.setItem(r, 0, QTableWidgetItem(row["model"]))
            cnt = self.store._query_one(
                "SELECT COUNT(*) c FROM listings WHERE search_id=?", (row["id"],))
            self.tbl_searches.setItem(r, 1, QTableWidgetItem(str(cnt["c"] if cnt else 0)))
            self.tbl_searches.setItem(r, 2, QTableWidgetItem(row["status"]))
            self.tbl_searches.setItem(r, 3, QTableWidgetItem(time.strftime("%m-%d %H:%M", time.localtime(row["created_at"]))))
        quotes = self.store.recent_quotes(30)
        self.tbl_quotes.setRowCount(0)
        for row in quotes:
            r = self.tbl_quotes.rowCount()
            self.tbl_quotes.insertRow(r)
            self.tbl_quotes.setItem(r, 0, QTableWidgetItem(row["model"]))
            self.tbl_quotes.setItem(r, 1, QTableWidgetItem(str(row["seller_price"])))
            self.tbl_quotes.setItem(r, 2, QTableWidgetItem(str(row["quoted_price"])))
            self.tbl_quotes.setItem(r, 3, QTableWidgetItem(time.strftime("%m-%d %H:%M", time.localtime(row["created_at"]))))

    # ---------------- 工具 ----------------
    def _show_status(self, msg: str):
        self.statusBar().showMessage(msg)
        log.info(msg)
