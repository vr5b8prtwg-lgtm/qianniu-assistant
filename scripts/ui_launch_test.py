# -*- coding: utf-8 -*-
"""界面启动测试（offscreen）：验证面板可创建、事件循环可运行、可正常退出。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.config import load_config
from app.store import Store
from app.ui.panel import MainPanel

app = QApplication([])
cfg = load_config()
store = Store(Path("data_test.db"))
panel = MainPanel(cfg, store)
panel.show()

state = {"quitted": False}


def quit_app():
    state["quitted"] = True
    app.quit()


QTimer.singleShot(2500, quit_app)
rc = app.exec()
panel.close()
panel.gf_thread.wait(2000)
print(f"事件循环退出码: {rc}, 正常退出: {state['quitted']}")
Path("data_test.db").unlink(missing_ok=True)
sys.exit(0 if state["quitted"] else 1)
