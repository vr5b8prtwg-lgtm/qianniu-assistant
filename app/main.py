# -*- coding: utf-8 -*-
"""程序入口。"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.config import APP_DIR, load_config
from app.store import Store


def setup_logging():
    log_path = APP_DIR / "app.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main() -> int:
    setup_logging()
    cfg = load_config()
    store = Store(APP_DIR / "data.db")
    app = QApplication(sys.argv)
    app.setApplicationName("千牛工作台助手")

    from app.ui.panel import MainPanel
    panel = MainPanel(cfg, store)
    panel.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
