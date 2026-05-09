# -*- coding: utf-8 -*-
"""
指纹库管理模块
==============

基于 SQLite 的轻量本地指纹库,与 eem_fingerprint 模块解耦.

表结构 (fingerprints):
    id            INTEGER PRIMARY KEY
    name          TEXT NOT NULL UNIQUE      指纹标识 (用户起的名字)
    category      TEXT                      水样类别 (生活污水/工业废水/雨水/地表水/...)
    source_file   TEXT                      原始 CSV 文件名
    blank_file    TEXT                      使用的空白参考文件名
    created_at    TEXT
    note          TEXT
    ex_json       TEXT NOT NULL             JSON 编码的 Ex 网格
    em_json       TEXT NOT NULL             JSON 编码的 Em 网格
    feature_blob  BLOB NOT NULL             特征向量 (np.float32 二进制)
    fri_json      TEXT NOT NULL             FRI 五区比例
    peaks_json    TEXT                      峰位 JSON
    stats_json    TEXT                      统计描述子 JSON

相似度: 余弦相似度 + 归一化欧式距离 (按用户要求).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np


SCHEMA = """
CREATE TABLE IF NOT EXISTS fingerprints (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    category     TEXT,
    source_file  TEXT,
    blank_file   TEXT,
    created_at   TEXT NOT NULL,
    note         TEXT,
    ex_json      TEXT NOT NULL,
    em_json      TEXT NOT NULL,
    feature_blob BLOB NOT NULL,
    fri_json     TEXT NOT NULL,
    peaks_json   TEXT,
    stats_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_category ON fingerprints(category);
"""


@dataclass
class LibraryEntry:
    """指纹库一条记录的内存映像."""
    id: int
    name: str
    category: str
    source_file: str
    blank_file: str
    created_at: str
    note: str
    ex: np.ndarray
    em: np.ndarray
    feature_vector: np.ndarray
    fri: Dict[str, float]
    peaks: List[Dict[str, float]]
    stats: Dict[str, float]


class FingerprintLibrary:
    """SQLite 指纹库, 支持建库/添加/删除/列表/检索."""

    def __init__(self, db_path: str = "eem_library.sqlite"):
        self.db_path = db_path
        # check_same_thread=False 允许从 ASGI 线程池跨线程使用同一连接;
        # 用 _lock 串行化所有写, 避免 SQLITE_BUSY.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ---------- 增删查改 ----------------------------------------------------
    def add(self, name: str, ex: np.ndarray, em: np.ndarray,
            feature_vector: np.ndarray, fri: Dict[str, float],
            peaks: List[Dict[str, float]], stats: Dict[str, float],
            category: str = "", source_file: str = "",
            blank_file: str = "", note: str = "") -> int:
        """添加一条指纹. 若 name 重复抛 sqlite3.IntegrityError."""
        feat = np.ascontiguousarray(feature_vector, dtype=np.float32)
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO fingerprints
                   (name, category, source_file, blank_file, created_at, note,
                    ex_json, em_json, feature_blob, fri_json, peaks_json, stats_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (name, category, source_file, blank_file,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"), note,
                 json.dumps(ex.tolist()),
                 json.dumps(em.tolist()),
                 feat.tobytes(),
                 json.dumps(fri),
                 json.dumps(peaks),
                 json.dumps(stats)))
            self._conn.commit()
            return cur.lastrowid

    def delete(self, entry_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM fingerprints WHERE id=?", (entry_id,))
            self._conn.commit()

    def update_meta(self, entry_id: int, name: Optional[str] = None,
                    category: Optional[str] = None,
                    note: Optional[str] = None) -> None:
        sets, vals = [], []
        if name is not None:
            sets.append("name=?"); vals.append(name)
        if category is not None:
            sets.append("category=?"); vals.append(category)
        if note is not None:
            sets.append("note=?"); vals.append(note)
        if not sets:
            return
        vals.append(entry_id)
        with self._lock:
            self._conn.execute(
                f"UPDATE fingerprints SET {','.join(sets)} WHERE id=?", vals)
            self._conn.commit()

    def list_summary(self) -> List[Dict]:
        """仅取摘要字段, 不还原大向量, 用于列表显示."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, name, category, source_file, blank_file,
                          created_at, note FROM fingerprints
                   ORDER BY id DESC""").fetchall()
        return [dict(r) for r in rows]

    def get(self, entry_id: int) -> LibraryEntry:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM fingerprints WHERE id=?", (entry_id,)).fetchone()
        if row is None:
            raise KeyError(f"id={entry_id} 不存在")
        return self._row_to_entry(row)

    def get_by_name(self, name: str) -> LibraryEntry:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM fingerprints WHERE name=?", (name,)).fetchone()
        if row is None:
            raise KeyError(f"name={name!r} 不存在")
        return self._row_to_entry(row)

    def all_entries(self) -> List[LibraryEntry]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM fingerprints ORDER BY id DESC").fetchall()
        return [self._row_to_entry(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) AS c FROM fingerprints").fetchone()["c"]

    # ---------- 检索 -------------------------------------------------------
    def search(self, query_vec: np.ndarray,
               top_k: int = 10,
               cosine_weight: float = 0.6,
               euclid_weight: float = 0.4
               ) -> List[Tuple[LibraryEntry, Dict[str, float]]]:
        """
        在库中检索与 query_vec 最相似的指纹, 按综合评分降序.

        相似度组合:
            score = cosine_weight * cos_sim + euclid_weight * (1 - eucl_norm/2)

        其中 eucl_norm 是单位化向量后的欧式距离 (范围 0~2).
        返回 [(entry, {cosine, euclid, score}), ...]
        """
        q = query_vec.astype(np.float64)
        qn = np.linalg.norm(q) or 1e-12
        qhat = q / qn

        results = []
        for entry in self.all_entries():
            v = entry.feature_vector.astype(np.float64)
            vn = np.linalg.norm(v) or 1e-12
            vhat = v / vn

            # 长度对齐 (理论上设备相同应一致, 否则裁到最短)
            n = min(qhat.size, vhat.size)
            cos = float(np.dot(qhat[:n], vhat[:n]))
            eucl = float(np.linalg.norm(qhat[:n] - vhat[:n]))      # ∈[0,2]
            eucl_sim = max(0.0, 1.0 - eucl / 2.0)                  # ∈[0,1]
            score = cosine_weight * max(cos, 0.0) + euclid_weight * eucl_sim
            results.append((entry, {
                "cosine_similarity": cos,
                "euclidean_distance": eucl,
                "score": score,
            }))

        results.sort(key=lambda x: x[1]["score"], reverse=True)
        return results[:top_k]

    def compare(self, id_a: int, id_b: int) -> Dict[str, float]:
        """两个库内指纹的成对比对 (返回 cosine / euclid / score)."""
        a = self.get(id_a)
        b = self.get(id_b)
        n = min(a.feature_vector.size, b.feature_vector.size)
        va = a.feature_vector[:n].astype(np.float64)
        vb = b.feature_vector[:n].astype(np.float64)
        na = np.linalg.norm(va) or 1e-12
        nb = np.linalg.norm(vb) or 1e-12
        cos = float(np.dot(va, vb) / (na * nb))
        eucl = float(np.linalg.norm(va / na - vb / nb))
        eucl_sim = max(0.0, 1.0 - eucl / 2.0)
        return {
            "cosine_similarity": cos,
            "euclidean_distance": eucl,
            "score": 0.6 * max(cos, 0.0) + 0.4 * eucl_sim,
        }

    # ---------- 工具 -------------------------------------------------------
    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> LibraryEntry:
        feat = np.frombuffer(row["feature_blob"], dtype=np.float32).copy()
        return LibraryEntry(
            id=row["id"],
            name=row["name"],
            category=row["category"] or "",
            source_file=row["source_file"] or "",
            blank_file=row["blank_file"] or "",
            created_at=row["created_at"] or "",
            note=row["note"] or "",
            ex=np.array(json.loads(row["ex_json"]), dtype=float),
            em=np.array(json.loads(row["em_json"]), dtype=float),
            feature_vector=feat,
            fri=json.loads(row["fri_json"]),
            peaks=json.loads(row["peaks_json"] or "[]"),
            stats=json.loads(row["stats_json"] or "{}"),
        )
