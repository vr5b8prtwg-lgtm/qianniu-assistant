# -*- coding: utf-8 -*-
"""SQLite 本地存储：会话、消息、型号、搜索结果、报价历史。"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ---------- 内部工具 ----------
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def _execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(sql, params)
                conn.commit()
            finally:
                conn.close()

    def _query(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        with self._lock:
            conn = self._conn()
            try:
                return conn.execute(sql, params).fetchall()
            finally:
                conn.close()

    def _query_one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        rows = self._query(sql, params)
        return rows[0] if rows else None

    # ---------- 建表 ----------
    def _init_db(self) -> None:
        sql = """
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            buyer_nick TEXT,
            buyer_id TEXT,
            created_at REAL,
            updated_at REAL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER,
            direction TEXT,
            content TEXT,
            content_type TEXT DEFAULT 'text',
            image_path TEXT,
            created_at REAL
        );
        CREATE TABLE IF NOT EXISTS models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER,
            model TEXT NOT NULL,
            brand TEXT,
            source TEXT,
            confidence REAL,
            created_at REAL
        );
        CREATE TABLE IF NOT EXISTS searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model TEXT NOT NULL,
            query TEXT,
            status TEXT,
            note TEXT,
            created_at REAL
        );
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_id INTEGER,
            item_id TEXT,
            title TEXT,
            price TEXT,
            seller TEXT,
            url TEXT,
            created_at REAL,
            UNIQUE(search_id, item_id)
        );
        CREATE TABLE IF NOT EXISTS quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model TEXT,
            seller_price REAL,
            quoted_price REAL,
            message TEXT,
            created_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_models_model ON models(model);
        CREATE INDEX IF NOT EXISTS idx_searches_model ON searches(model);
        CREATE INDEX IF NOT EXISTS idx_quotes_model ON quotes(model);
        """
        with self._lock:
            conn = self._conn()
            try:
                conn.executescript(sql)
                conn.commit()
            finally:
                conn.close()

    # ---------- 会话 / 消息 ----------
    def ensure_conversation(self, buyer_nick: str = "", buyer_id: str = "") -> int:
        now = time.time()
        if buyer_id:
            row = self._query_one(
                "SELECT id FROM conversations WHERE buyer_id=? LIMIT 1", (buyer_id,)
            )
            if row:
                self._execute(
                    "UPDATE conversations SET updated_at=? WHERE id=?", (now, row["id"])
                )
                return int(row["id"])
        conn = self._conn()
        try:
            cur = conn.execute(
                "INSERT INTO conversations (buyer_nick, buyer_id, created_at, updated_at) VALUES (?,?,?,?)",
                (buyer_nick, buyer_id, now, now),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def add_message(self, conversation_id: int, direction: str, content: str,
                    content_type: str = "text", image_path: str = "") -> int:
        now = time.time()
        conn = self._conn()
        try:
            cur = conn.execute(
                "INSERT INTO messages (conversation_id, direction, content, content_type, image_path, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (conversation_id, direction, content, content_type, image_path, now),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def recent_messages(self, conversation_id: int, limit: int = 50) -> List[sqlite3.Row]:
        return self._query(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        )

    # ---------- 型号 ----------
    def add_model(self, conversation_id: int, model: str, brand: str = "",
                  source: str = "", confidence: float = 0.0) -> int:
        now = time.time()
        conn = self._conn()
        try:
            cur = conn.execute(
                "INSERT INTO models (conversation_id, model, brand, source, confidence, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (conversation_id, model, brand, source, confidence, now),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    # ---------- 搜索 ----------
    def add_search(self, model: str, query: str, status: str = "ok", note: str = "") -> int:
        now = time.time()
        conn = self._conn()
        try:
            cur = conn.execute(
                "INSERT INTO searches (model, query, status, note, created_at) VALUES (?,?,?,?,?)",
                (model, query, status, note, now),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def add_listings(self, search_id: int, listings: List[Dict[str, Any]]) -> None:
        now = time.time()
        with self._lock:
            conn = self._conn()
            try:
                for it in listings:
                    conn.execute(
                        "INSERT OR IGNORE INTO listings (search_id, item_id, title, price, seller, url, created_at) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (search_id, it.get("item_id", ""), it.get("title", ""),
                         it.get("price", ""), it.get("seller", ""), it.get("url", ""), now),
                    )
                conn.commit()
            finally:
                conn.close()

    def get_cached_search(self, model: str, max_age_hours: float = 24.0) -> Optional[Dict[str, Any]]:
        """返回最近一次成功搜索及其结果；超过 max_age_hours 或没有结果时返回 None。"""
        cutoff = time.time() - max_age_hours * 3600
        row = self._query_one(
            "SELECT * FROM searches WHERE model=? AND status='ok' AND created_at>? "
            "ORDER BY id DESC LIMIT 1",
            (model, cutoff),
        )
        if not row:
            return None
        listings = self._query(
            "SELECT * FROM listings WHERE search_id=? ORDER BY id", (row["id"],)
        )
        if not listings:
            return None
        return {
            "search_id": row["id"],
            "model": row["model"],
            "created_at": row["created_at"],
            "listings": [dict(r) for r in listings],
        }

    def recent_searches(self, limit: int = 50) -> List[sqlite3.Row]:
        return self._query("SELECT * FROM searches ORDER BY id DESC LIMIT ?", (limit,))

    # ---------- 报价 ----------
    def add_quote(self, model: str, seller_price: float, quoted_price: float, message: str) -> int:
        now = time.time()
        conn = self._conn()
        try:
            cur = conn.execute(
                "INSERT INTO quotes (model, seller_price, quoted_price, message, created_at) VALUES (?,?,?,?,?)",
                (model, seller_price, quoted_price, message, now),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def recent_quotes(self, limit: int = 50) -> List[sqlite3.Row]:
        return self._query("SELECT * FROM quotes ORDER BY id DESC LIMIT ?", (limit,))
