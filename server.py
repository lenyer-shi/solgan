# -*- coding: utf-8 -*-
"""
水质三维荧光光谱指纹工具 - FastAPI 后端服务
=================================================
依赖:
    pip install fastapi uvicorn[standard] python-multipart numpy pandas

启动:
    python server.py                  # 默认 0.0.0.0:8000
    或: uvicorn server:app --reload --host 0.0.0.0 --port 8000

REST API:
    POST /api/process            上传 blank+sample 进行预处理与特征提取
    GET  /api/library/list       列出库内全部指纹
    POST /api/library/add        将刚处理好的指纹写入库 (需先 process)
    DELETE /api/library/{id}     删除条目
    POST /api/library/search     按当前指纹检索
    POST /api/compare            两组样本一对一比对
    GET  /                       前端 (static/index.html)
"""
from __future__ import annotations

import io
import os
import sys
import uuid
import time
import json
from typing import Optional, List, Dict, Any

import numpy as np
import pandas as pd

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 复用桌面端模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eem_fingerprint import (                                # type: ignore
    EEMProcessor, extract_fingerprint, EEM, Fingerprint, FRI_REGIONS,
    FRI_REGION_NAMES_CN, read_eem_csv,
)
from fingerprint_db import FingerprintLibrary, LibraryEntry  # type: ignore


# ---------- 应用 ----------------------------------------------------------
app = FastAPI(title="EEM Fingerprint API", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"],
)

# 静态前端 (static 目录)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------- 全局状态 (内存会话池 + 单库) ---------------------------------
LIB_PATH = os.environ.get("EEM_LIB", "eem_library.sqlite")
_lib: Optional[FingerprintLibrary] = None


def lib() -> FingerprintLibrary:
    global _lib
    if _lib is None:
        _lib = FingerprintLibrary(LIB_PATH)
    return _lib


# 处理结果会话: 浏览器 process 后保留 30 分钟以便 add/search
_SESSIONS: Dict[str, Dict[str, Any]] = {}
_SESS_TTL = 30 * 60


def _gc():
    now = time.time()
    for k in list(_SESSIONS):
        if now - _SESSIONS[k].get("ts", 0) > _SESS_TTL:
            _SESSIONS.pop(k, None)


# ---------- 工具函数 ------------------------------------------------------
def _save_upload(upload: UploadFile) -> str:
    """把上传文件落盘到 tmp 目录,返回路径."""
    tmp = os.path.join(os.path.dirname(__file__), ".tmp_uploads")
    os.makedirs(tmp, exist_ok=True)
    path = os.path.join(tmp, f"{uuid.uuid4().hex}_{upload.filename}")
    with open(path, "wb") as f:
        f.write(upload.file.read())
    return path


def _eem_to_dict(eem: EEM) -> Dict[str, Any]:
    M = np.nan_to_num(eem.intensity, nan=0.0)
    return {
        "ex": eem.ex.tolist(),
        "em": eem.em.tolist(),
        "z":  M.tolist(),
        "shape": list(M.shape),
        "max":  float(M.max()) if M.size else 0.0,
        "min":  float(M.min()) if M.size else 0.0,
    }


def _fp_to_dict(fp: Fingerprint) -> Dict[str, Any]:
    return {
        "fri_volumes":   fp.fri_volumes,
        "fri_fractions": fp.fri_fractions,
        "peaks":         fp.peaks,
        "stats":         fp.stats,
    }


# ---------- 请求模型 ------------------------------------------------------
class SearchRequest(BaseModel):
    session_id: str
    top_k: int = 10
    cosine_weight: float = 0.6
    euclid_weight: float = 0.4


class AddRequest(BaseModel):
    session_id: str
    name: str
    category: str = ""
    note: str = ""


class CompareRequest(BaseModel):
    session_a: str
    session_b: str


# ---------- 路由 ----------------------------------------------------------
@app.get("/")
def root():
    idx = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(idx):
        return FileResponse(idx)
    return {"msg": "EEM Fingerprint API. Frontend not deployed; visit /docs."}


@app.get("/api/health")
def health():
    return {"status": "ok", "library": LIB_PATH,
            "library_count": lib().count(),
            "sessions": len(_SESSIONS)}


@app.get("/api/fri/regions")
def fri_regions():
    """返回 FRI 五区域的定义和中文名 (前端用作展示标签)."""
    return {
        "regions": [
            {"key": k,
             "name_cn": FRI_REGION_NAMES_CN.get(k, k),
             "ex": list(FRI_REGIONS[k][0]),
             "em": list(FRI_REGIONS[k][1])}
            for k in FRI_REGIONS
        ]
    }


@app.get("/api/library/list")
def list_library():
    rows = lib().list_summary()
    return {"items": rows, "total": len(rows)}


@app.post("/api/process")
def process(
    blank: UploadFile = File(...),
    sample: UploadFile = File(...),
    agg_method: str = Form("median"),
    em_min: float = Form(200.0),
    em_max: float = Form(600.0),
    ex_keep_below: float = Form(600.0),
    rayleigh_band: float = Form(15.0),
    raman_band: float = Form(15.0),
    sg_window: int = Form(11),
    sg_poly: int = Form(3),
):
    """上传 blank + sample, 返回预处理后的 EEM 与指纹特征."""
    _gc()
    try:
        bp = _save_upload(blank)
        sp = _save_upload(sample)
        proc = EEMProcessor(
            rayleigh_band=rayleigh_band, raman_band=raman_band,
            sg_window=sg_window, sg_poly=sg_poly,
            agg_method=agg_method,
            em_range=(em_min, em_max),
            ex_keep_below=ex_keep_below,
        )
        b = proc.load_and_aggregate(bp)
        s = proc.load_and_aggregate(sp)
        corr = proc.correct(s, b)
        fp = extract_fingerprint(corr)

        sid = uuid.uuid4().hex
        _SESSIONS[sid] = {
            "ts": time.time(),
            "fp": fp, "raw": s, "corr": corr,
            "blank_name": blank.filename,
            "sample_name": sample.filename,
            "blank_path": bp, "sample_path": sp,
        }

        return {
            "session_id": sid,
            "blank_name": blank.filename,
            "sample_name": sample.filename,
            "raw":       _eem_to_dict(s),
            "corrected": _eem_to_dict(corr),
            "fingerprint": _fp_to_dict(fp),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"处理失败: {e}")


@app.post("/api/library/add")
def library_add(req: AddRequest):
    sess = _SESSIONS.get(req.session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session 已过期, 请重新处理")
    fp: Fingerprint = sess["fp"]
    corr: EEM = sess["corr"]
    try:
        new_id = lib().add(
            name=req.name.strip(),
            ex=corr.ex, em=corr.em,
            feature_vector=fp.feature_vector,
            fri=fp.fri_fractions,
            peaks=fp.peaks, stats=fp.stats,
            category=req.category.strip(),
            source_file=sess.get("sample_name", ""),
            blank_file=sess.get("blank_name", ""),
            note=req.note.strip(),
        )
        return {"id": new_id, "ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/library/{entry_id}")
def library_delete(entry_id: int):
    lib().delete(entry_id)
    return {"ok": True}


@app.post("/api/library/search")
def library_search(req: SearchRequest):
    sess = _SESSIONS.get(req.session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session 已过期, 请重新处理")
    fp: Fingerprint = sess["fp"]
    res = lib().search(
        fp.feature_vector, top_k=req.top_k,
        cosine_weight=req.cosine_weight,
        euclid_weight=req.euclid_weight,
    )
    out = []
    for entry, m in res:
        # 重建小型 EEM 供前端预览
        ex, em = entry.ex, entry.em
        if entry.feature_vector.size == ex.size * em.size:
            M = entry.feature_vector.reshape(ex.size, em.size).tolist()
        else:
            M = []
        out.append({
            "id": entry.id, "name": entry.name,
            "category": entry.category,
            "source_file": entry.source_file,
            "created_at": entry.created_at,
            "metrics": m,
            "fri_fractions": entry.fri,
            "ex": ex.tolist(), "em": em.tolist(),
            "z": M,
        })
    return {"results": out}


@app.get("/api/library/{entry_id}")
def library_get(entry_id: int):
    try:
        e = lib().get(entry_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
    if e.feature_vector.size == e.ex.size * e.em.size:
        z = e.feature_vector.reshape(e.ex.size, e.em.size).tolist()
    else:
        z = []
    return {
        "id": e.id, "name": e.name, "category": e.category,
        "source_file": e.source_file, "blank_file": e.blank_file,
        "created_at": e.created_at, "note": e.note,
        "fri_fractions": e.fri, "peaks": e.peaks, "stats": e.stats,
        "ex": e.ex.tolist(), "em": e.em.tolist(), "z": z,
    }


@app.post("/api/compare")
def compare(req: CompareRequest):
    a = _SESSIONS.get(req.session_a)
    b = _SESSIONS.get(req.session_b)
    if not a or not b:
        raise HTTPException(status_code=404,
                            detail="必须先调用 /api/process 处理 A 和 B 各一次")
    va = a["fp"].feature_vector
    vb = b["fp"].feature_vector
    n = min(va.size, vb.size)
    va = va[:n].astype(np.float64); vb = vb[:n].astype(np.float64)
    na = float(np.linalg.norm(va)) or 1e-12
    nb = float(np.linalg.norm(vb)) or 1e-12
    cos = float(np.dot(va, vb) / (na * nb))
    eucl = float(np.linalg.norm(va / na - vb / nb))
    score = 0.6 * max(cos, 0.0) + 0.4 * max(0.0, 1.0 - eucl / 2.0)
    return {
        "cosine_similarity": cos,
        "euclidean_distance": eucl,
        "score": score,
        "a": {"name": a.get("sample_name", ""), "corrected": _eem_to_dict(a["corr"])},
        "b": {"name": b.get("sample_name", ""), "corrected": _eem_to_dict(b["corr"])},
    }


# ---------- 启动 ----------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("EEM_HOST", "0.0.0.0")
    port = int(os.environ.get("EEM_PORT", "8000"))
    print(f"EEM Fingerprint Server running on http://{host}:{port}")
    print(f"  API docs:  http://localhost:{port}/docs")
    print(f"  Frontend:  http://localhost:{port}/")
    uvicorn.run("server:app", host=host, port=port, reload=False)
