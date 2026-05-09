# -*- coding: utf-8 -*-
"""
水质三维荧光光谱指纹工具 - PyQt5 图形化界面
================================================

功能模块 (按 Tab 组织):
  Tab 1  数据加载与预处理   - 选择 blank.csv / sample.csv, 配置预处理参数, 一键运行
  Tab 2  指纹特征提取与可视化 - 等高线图 / 伪彩图 / FRI 柱状图 / 峰位/统计表格
  Tab 3  指纹库管理         - 创建/打开 .sqlite 库, 入库/删除/查看
  Tab 4  指纹检索           - 用当前样本作为查询向量, 检索库内最相似指纹
  Tab 5  双样本比对         - 任选两个样本/库内条目, 计算余弦+欧式相似度

依赖:
  PyQt5, matplotlib, numpy, pandas
  以及同目录下的 eem_fingerprint.py / fingerprint_db.py / eem_visualizer.py

启动:
  python eem_gui.py
"""
from __future__ import annotations

import os
import sys
import traceback
from typing import Optional

import numpy as np
import pandas as pd

from PyQt5 import QtCore, QtGui, QtWidgets

# 本工程模块
from eem_fingerprint import (
    EEMProcessor, extract_fingerprint, EEM, Fingerprint,
    FRI_REGIONS, FRI_REGION_NAMES_CN,
)
from fingerprint_db import FingerprintLibrary, LibraryEntry
from eem_visualizer import EEMCanvas, ContourPanel


APP_TITLE = "水质三维荧光光谱指纹工具 (EEM Fingerprint)"


# =============================================================================
# Tab 1: 预处理 + 特征提取
# =============================================================================
class AnalysisTab(QtWidgets.QWidget):
    """加载数据 → 预处理 → 提取指纹 → 可视化."""

    fingerprintReady = QtCore.pyqtSignal(object, object, object)
    # 信号载荷: (Fingerprint, raw_eem: EEM, corrected_eem: EEM)

    def __init__(self):
        super().__init__()
        self.blank_path: Optional[str] = None
        self.sample_path: Optional[str] = None
        self.current_fp: Optional[Fingerprint] = None
        self.current_raw: Optional[EEM] = None
        self.current_corr: Optional[EEM] = None
        self._build_ui()

    # ---------------------- UI ----------------------------------------------
    def _build_ui(self):
        layout = QtWidgets.QHBoxLayout(self)
        # ----- 左侧控制面板 -----
        left = QtWidgets.QFrame()
        left.setFrameShape(QtWidgets.QFrame.StyledPanel)
        left.setMaximumWidth(320)
        ll = QtWidgets.QVBoxLayout(left)

        # ---- 文件加载 (EEM 文件加载按钮区) ------------------------------
        gb_file = QtWidgets.QGroupBox("EEM 文件加载")
        fv = QtWidgets.QVBoxLayout(gb_file)
        fv.setSpacing(6)

        # 空白(纯水)
        fv.addWidget(QtWidgets.QLabel("空白 (纯水) EEM:"))
        row_b = QtWidgets.QHBoxLayout()
        self.btn_blank = QtWidgets.QPushButton("📂 加载空白 EEM 文件…")
        self.btn_blank.setMinimumHeight(32)
        self.btn_blank.setStyleSheet(
            "QPushButton{background:#eef3fb;border:1px solid #4C72B0;"
            "color:#1f3a68;font-weight:600;border-radius:4px;padding:4px 10px;}"
            "QPushButton:hover{background:#dbe7f5;}"
        )
        self.btn_blank.clicked.connect(self._pick_blank)
        self.btn_blank_clear = QtWidgets.QPushButton("✕")
        self.btn_blank_clear.setFixedWidth(28)
        self.btn_blank_clear.setToolTip("清除已选空白文件")
        self.btn_blank_clear.clicked.connect(self._clear_blank)
        row_b.addWidget(self.btn_blank, stretch=1)
        row_b.addWidget(self.btn_blank_clear)
        fv.addLayout(row_b)
        self.lbl_blank = QtWidgets.QLabel("(未选择)")
        self.lbl_blank.setStyleSheet("color:#666;padding-left:4px;")
        self.lbl_blank.setWordWrap(True)
        fv.addWidget(self.lbl_blank)

        # 分隔
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        fv.addWidget(line)

        # 样本
        fv.addWidget(QtWidgets.QLabel("样本 EEM:"))
        row_s = QtWidgets.QHBoxLayout()
        self.btn_sample = QtWidgets.QPushButton("📂 加载样本 EEM 文件…")
        self.btn_sample.setMinimumHeight(32)
        self.btn_sample.setStyleSheet(
            "QPushButton{background:#fbeeee;border:1px solid #C44E52;"
            "color:#6e2024;font-weight:600;border-radius:4px;padding:4px 10px;}"
            "QPushButton:hover{background:#f5dbdc;}"
        )
        self.btn_sample.clicked.connect(self._pick_sample)
        self.btn_sample_clear = QtWidgets.QPushButton("✕")
        self.btn_sample_clear.setFixedWidth(28)
        self.btn_sample_clear.setToolTip("清除已选样本文件")
        self.btn_sample_clear.clicked.connect(self._clear_sample)
        row_s.addWidget(self.btn_sample, stretch=1)
        row_s.addWidget(self.btn_sample_clear)
        fv.addLayout(row_s)
        self.lbl_sample = QtWidgets.QLabel("(未选择)")
        self.lbl_sample.setStyleSheet("color:#666;padding-left:4px;")
        self.lbl_sample.setWordWrap(True)
        fv.addWidget(self.lbl_sample)

        ll.addWidget(gb_file)

        # 预处理参数
        gb_proc = QtWidgets.QGroupBox("预处理参数")
        pl = QtWidgets.QFormLayout(gb_proc)

        self.cmb_agg = QtWidgets.QComboBox()
        self.cmb_agg.addItems(["median", "hampel", "tmean", "mean"])
        self.cmb_agg.setToolTip("同 Ex 多通道聚合方法,中位数对水质波动最稳健")

        self.spn_em_min = QtWidgets.QSpinBox()
        self.spn_em_min.setRange(200, 800); self.spn_em_min.setValue(200)
        self.spn_em_max = QtWidgets.QSpinBox()
        self.spn_em_max.setRange(200, 900); self.spn_em_max.setValue(600)
        self.spn_ex_keep = QtWidgets.QSpinBox()
        self.spn_ex_keep.setRange(200, 900); self.spn_ex_keep.setValue(600)

        self.spn_ray = QtWidgets.QDoubleSpinBox()
        self.spn_ray.setRange(0.0, 50.0); self.spn_ray.setValue(15.0)
        self.spn_raman = QtWidgets.QDoubleSpinBox()
        self.spn_raman.setRange(0.0, 50.0); self.spn_raman.setValue(15.0)

        self.spn_sg_w = QtWidgets.QSpinBox()
        self.spn_sg_w.setRange(3, 51); self.spn_sg_w.setValue(11)
        self.spn_sg_w.setSingleStep(2)
        self.spn_sg_p = QtWidgets.QSpinBox()
        self.spn_sg_p.setRange(1, 7); self.spn_sg_p.setValue(3)

        pl.addRow("通道聚合", self.cmb_agg)
        pl.addRow("Em 最小 (nm)", self.spn_em_min)
        pl.addRow("Em 最大 (nm)", self.spn_em_max)
        pl.addRow("Ex 上限 (nm)", self.spn_ex_keep)
        pl.addRow("瑞利屏蔽带宽 (nm)", self.spn_ray)
        pl.addRow("拉曼屏蔽带宽 (nm)", self.spn_raman)
        pl.addRow("SG 窗口", self.spn_sg_w)
        pl.addRow("SG 多项式阶", self.spn_sg_p)

        ll.addWidget(gb_proc)

        # 运行按钮
        self.btn_run = QtWidgets.QPushButton("▶ 运行预处理 + 特征提取")
        self.btn_run.clicked.connect(self._run)
        self.btn_run.setStyleSheet(
            "QPushButton{font-weight:bold;padding:8px;background:#4C72B0;color:white;border-radius:4px;}"
            "QPushButton:hover{background:#5d83c1;}"
        )
        ll.addWidget(self.btn_run)
        ll.addStretch(1)

        # 状态
        self.lbl_status = QtWidgets.QLabel("就绪")
        self.lbl_status.setStyleSheet("color:#666;")
        ll.addWidget(self.lbl_status)

        # ----- 右侧: 可视化 + 数值结果 -----
        right = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(right)

        # 视图切换 (等高线/伪彩/FRI柱)
        self.view_tabs = QtWidgets.QTabWidget()
        self.panel_contour = ContourPanel()                # 带着色开关
        self.canvas_pcolor = EEMCanvas()
        self.panel_raw = ContourPanel()                    # 原始也用同款
        self.canvas_fri = EEMCanvas()
        self.view_tabs.addTab(self.panel_contour, "等高线 (corrected)")
        self.view_tabs.addTab(self.canvas_pcolor, "伪彩图 (corrected)")
        self.view_tabs.addTab(self.panel_raw, "原始 (raw)")
        self.view_tabs.addTab(self.canvas_fri, "FRI 占比")
        rl.addWidget(self.view_tabs, stretch=3)

        # 数值结果
        bottom = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.tbl_fri = self._make_table(["区域", "体积", "占比"])
        self.tbl_peaks = self._make_table(["#", "Ex(nm)", "Em(nm)", "强度"])
        self.tbl_stats = self._make_table(["指标", "数值"])
        for w, title in [(self.tbl_fri, "FRI 五区域"),
                         (self.tbl_peaks, "主荧光峰"),
                         (self.tbl_stats, "统计描述子")]:
            box = QtWidgets.QGroupBox(title)
            v = QtWidgets.QVBoxLayout(box); v.addWidget(w)
            bottom.addWidget(box)
        rl.addWidget(bottom, stretch=2)

        layout.addWidget(left)
        layout.addWidget(right, stretch=1)

    @staticmethod
    def _make_table(headers):
        t = QtWidgets.QTableWidget()
        t.setColumnCount(len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        return t

    # ---------------------- 操作回调 -----------------------------------------
    def _pick_blank(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择空白(纯水) EEM CSV", "",
            "EEM CSV (*.csv);;所有文件 (*.*)")
        if path:
            self.blank_path = path
            self.lbl_blank.setText("✔ " + os.path.basename(path))
            self.lbl_blank.setToolTip(path)
            self.lbl_blank.setStyleSheet(
                "color:#1f3a68;padding-left:4px;font-weight:bold;")

    def _pick_sample(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择样本 EEM CSV", "",
            "EEM CSV (*.csv);;所有文件 (*.*)")
        if path:
            self.sample_path = path
            self.lbl_sample.setText("✔ " + os.path.basename(path))
            self.lbl_sample.setToolTip(path)
            self.lbl_sample.setStyleSheet(
                "color:#6e2024;padding-left:4px;font-weight:bold;")

    def _clear_blank(self):
        self.blank_path = None
        self.lbl_blank.setText("(未选择)")
        self.lbl_blank.setToolTip("")
        self.lbl_blank.setStyleSheet("color:#666;padding-left:4px;")

    def _clear_sample(self):
        self.sample_path = None
        self.lbl_sample.setText("(未选择)")
        self.lbl_sample.setToolTip("")
        self.lbl_sample.setStyleSheet("color:#666;padding-left:4px;")

    def _run(self):
        if not self.blank_path or not self.sample_path:
            QtWidgets.QMessageBox.warning(
                self, "缺少文件", "请先选择 blank 和 sample CSV.")
            return
        self.lbl_status.setText("处理中…")
        QtWidgets.QApplication.processEvents()
        try:
            proc = EEMProcessor(
                rayleigh_band=self.spn_ray.value(),
                raman_band=self.spn_raman.value(),
                sg_window=self.spn_sg_w.value(),
                sg_poly=self.spn_sg_p.value(),
                agg_method=self.cmb_agg.currentText(),
                em_range=(self.spn_em_min.value(), self.spn_em_max.value()),
                ex_keep_below=self.spn_ex_keep.value(),
            )
            blank = proc.load_and_aggregate(self.blank_path)
            sample = proc.load_and_aggregate(self.sample_path)
            corr = proc.correct(sample, blank)
            fp = extract_fingerprint(corr)

            self.current_fp = fp
            self.current_raw = sample
            self.current_corr = corr
            self._render(fp, sample, corr)
            self.fingerprintReady.emit(fp, sample, corr)
            self.lbl_status.setText(
                f"完成: Ex={len(corr.ex)} 个, Em={len(corr.em)} 点")
        except Exception as e:
            self.lbl_status.setText("失败")
            QtWidgets.QMessageBox.critical(
                self, "处理失败", f"{e}\n\n{traceback.format_exc()}")

    def _render(self, fp: Fingerprint, raw: EEM, corr: EEM):
        self.panel_contour.plot(
            corr.ex, corr.em, corr.intensity,
            title="Sample EEM (corrected)")
        self.canvas_pcolor.plot_pcolor(
            corr.ex, corr.em, corr.intensity,
            title="Sample EEM (corrected, pseudo-color)")
        self.panel_raw.plot(
            raw.ex, raw.em, np.nan_to_num(raw.intensity),
            title="Sample EEM (raw, after dark + aggregation)")
        self.canvas_fri.plot_fri_bar(fp.fri_fractions,
                                     name_map=FRI_REGION_NAMES_CN)

        # FRI 表 (中文标注)
        self.tbl_fri.setRowCount(len(fp.fri_volumes))
        for r, k in enumerate(fp.fri_volumes):
            label = FRI_REGION_NAMES_CN.get(k, k)
            item = QtWidgets.QTableWidgetItem(label)
            item.setToolTip(k)                # 悬停显示英文 key
            self.tbl_fri.setItem(r, 0, item)
            self.tbl_fri.setItem(r, 1, QtWidgets.QTableWidgetItem(
                f"{fp.fri_volumes[k]:.3e}"))
            self.tbl_fri.setItem(r, 2, QtWidgets.QTableWidgetItem(
                f"{fp.fri_fractions[k]*100:.2f}%"))

        # 峰表
        self.tbl_peaks.setRowCount(len(fp.peaks))
        for r, p in enumerate(fp.peaks):
            self.tbl_peaks.setItem(r, 0, QtWidgets.QTableWidgetItem(str(r + 1)))
            self.tbl_peaks.setItem(r, 1, QtWidgets.QTableWidgetItem(
                f"{p['ex']:.1f}"))
            self.tbl_peaks.setItem(r, 2, QtWidgets.QTableWidgetItem(
                f"{p['em']:.1f}"))
            self.tbl_peaks.setItem(r, 3, QtWidgets.QTableWidgetItem(
                f"{p['intensity']:.3e}"))

        # 统计表
        rows = list(fp.stats.items())
        self.tbl_stats.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.tbl_stats.setItem(r, 0, QtWidgets.QTableWidgetItem(k))
            self.tbl_stats.setItem(r, 1, QtWidgets.QTableWidgetItem(
                f"{v:.4g}"))


# =============================================================================
# Tab 3: 指纹库管理
# =============================================================================
class LibraryTab(QtWidgets.QWidget):
    """打开/创建库, 入库/删除/查看条目."""

    libraryChanged = QtCore.pyqtSignal()  # 内容变化时通知其他 tab 刷新

    def __init__(self, get_current_fingerprint_callback):
        super().__init__()
        self.lib: Optional[FingerprintLibrary] = None
        self._get_current = get_current_fingerprint_callback
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # 顶部: 库文件选择
        top = QtWidgets.QHBoxLayout()
        self.lbl_db = QtWidgets.QLabel("(未打开库)")
        btn_open = QtWidgets.QPushButton("打开/新建 .sqlite")
        btn_open.clicked.connect(self._open_db)
        top.addWidget(QtWidgets.QLabel("当前库:"))
        top.addWidget(self.lbl_db, stretch=1)
        top.addWidget(btn_open)
        layout.addLayout(top)

        # 中部: 条目表
        self.tbl = QtWidgets.QTableWidget()
        self.tbl.setColumnCount(7)
        self.tbl.setHorizontalHeaderLabels(
            ["ID", "名称", "类别", "原始文件", "空白", "时间", "备注"])
        self.tbl.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)
        self.tbl.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows)
        self.tbl.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.tbl, stretch=1)

        # 底部: 操作
        btns = QtWidgets.QHBoxLayout()
        self.btn_add = QtWidgets.QPushButton("+ 入库 (当前样本)")
        self.btn_del = QtWidgets.QPushButton("− 删除选中")
        self.btn_refresh = QtWidgets.QPushButton("🗘 刷新")
        self.btn_view = QtWidgets.QPushButton("👁 查看 EEM")
        for b in (self.btn_add, self.btn_del, self.btn_refresh, self.btn_view):
            btns.addWidget(b)
        btns.addStretch(1)
        layout.addLayout(btns)

        self.btn_add.clicked.connect(self._add_current)
        self.btn_del.clicked.connect(self._delete_selected)
        self.btn_refresh.clicked.connect(self._refresh)
        self.btn_view.clicked.connect(self._view_selected)

    def _open_db(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "选择/新建指纹库 (.sqlite)", "eem_library.sqlite",
            "SQLite (*.sqlite *.db);;所有文件 (*)",
            options=QtWidgets.QFileDialog.DontConfirmOverwrite)
        if not path:
            return
        if self.lib is not None:
            self.lib.close()
        self.lib = FingerprintLibrary(path)
        self.lbl_db.setText(path)
        self._refresh()
        self.libraryChanged.emit()

    def _refresh(self):
        if self.lib is None:
            return
        rows = self.lib.list_summary()
        self.tbl.setRowCount(len(rows))
        for r, item in enumerate(rows):
            for c, k in enumerate(["id", "name", "category", "source_file",
                                   "blank_file", "created_at", "note"]):
                cell = QtWidgets.QTableWidgetItem(str(item.get(k, "")))
                cell.setData(QtCore.Qt.UserRole, item["id"])
                self.tbl.setItem(r, c, cell)

    def _add_current(self):
        if self.lib is None:
            QtWidgets.QMessageBox.warning(self, "未打开库",
                                          "请先打开/新建一个 .sqlite 库.")
            return
        ctx = self._get_current()
        if ctx is None:
            QtWidgets.QMessageBox.warning(self, "无样本",
                                          "请先在 [分析] 页面运行一次预处理.")
            return
        fp, raw, corr, blank_path, sample_path = ctx
        default_name = os.path.splitext(os.path.basename(sample_path or "sample"))[0]
        name, ok = QtWidgets.QInputDialog.getText(
            self, "入库", "请输入指纹名称:", text=default_name)
        if not ok or not name.strip():
            return
        category, _ = QtWidgets.QInputDialog.getText(
            self, "类别", "类别 (可选, 如: 工业废水/生活污水/雨水/地表水):")
        note, _ = QtWidgets.QInputDialog.getMultiLineText(
            self, "备注", "备注 (可选):")
        try:
            self.lib.add(
                name=name.strip(),
                ex=corr.ex, em=corr.em,
                feature_vector=fp.feature_vector,
                fri=fp.fri_fractions,
                peaks=fp.peaks, stats=fp.stats,
                category=category.strip(),
                source_file=os.path.basename(sample_path or ""),
                blank_file=os.path.basename(blank_path or ""),
                note=note.strip(),
            )
            self._refresh()
            self.libraryChanged.emit()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "入库失败", str(e))

    def _delete_selected(self):
        rows = sorted({i.row() for i in self.tbl.selectedItems()}, reverse=True)
        if not rows:
            return
        ans = QtWidgets.QMessageBox.question(
            self, "确认删除", f"确定删除 {len(rows)} 条指纹?")
        if ans != QtWidgets.QMessageBox.Yes:
            return
        for r in rows:
            entry_id = int(self.tbl.item(r, 0).text())
            self.lib.delete(entry_id)
        self._refresh()
        self.libraryChanged.emit()

    def _view_selected(self):
        row_set = {i.row() for i in self.tbl.selectedItems()}
        if not row_set:
            return
        r = next(iter(row_set))
        entry = self.lib.get(int(self.tbl.item(r, 0).text()))
        # 重建 EEM 用于绘图: feature_vector 已展平归一化, 这里恢复矩阵形状
        ex, em = entry.ex, entry.em
        if entry.feature_vector.size == ex.size * em.size:
            M = entry.feature_vector.reshape(ex.size, em.size)
        else:
            M = entry.feature_vector
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"指纹查看: {entry.name}")
        dlg.resize(800, 600)
        v = QtWidgets.QVBoxLayout(dlg)
        canv = EEMCanvas()
        canv.plot_contour(ex, em, M,
                          title=f"{entry.name} ({entry.category})")
        v.addWidget(canv)
        dlg.exec_()


# =============================================================================
# Tab 4: 检索
# =============================================================================
class SearchTab(QtWidgets.QWidget):
    def __init__(self, get_current_fingerprint_callback,
                 get_library_callback):
        super().__init__()
        self._get_current = get_current_fingerprint_callback
        self._get_lib = get_library_callback
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        top = QtWidgets.QHBoxLayout()
        self.spn_topk = QtWidgets.QSpinBox()
        self.spn_topk.setRange(1, 100); self.spn_topk.setValue(10)
        self.spn_w_cos = QtWidgets.QDoubleSpinBox()
        self.spn_w_cos.setRange(0, 1); self.spn_w_cos.setValue(0.6)
        self.spn_w_cos.setSingleStep(0.05)
        self.spn_w_eu = QtWidgets.QDoubleSpinBox()
        self.spn_w_eu.setRange(0, 1); self.spn_w_eu.setValue(0.4)
        self.spn_w_eu.setSingleStep(0.05)
        btn = QtWidgets.QPushButton("🔍 用当前样本检索")
        btn.clicked.connect(self._search)
        btn.setStyleSheet(
            "QPushButton{padding:6px;background:#55A868;color:white;font-weight:bold;border-radius:4px;}")

        for w, lab in [(self.spn_topk, "Top-K"),
                       (self.spn_w_cos, "余弦权重"),
                       (self.spn_w_eu, "欧式权重")]:
            top.addWidget(QtWidgets.QLabel(lab))
            top.addWidget(w)
        top.addStretch(1)
        top.addWidget(btn)
        layout.addLayout(top)

        # 结果表
        self.tbl = QtWidgets.QTableWidget()
        self.tbl.setColumnCount(6)
        self.tbl.setHorizontalHeaderLabels(
            ["排名", "ID", "名称", "类别", "余弦相似度", "欧式距离"])
        self.tbl.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)
        self.tbl.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows)
        self.tbl.cellDoubleClicked.connect(self._compare_with_top)
        layout.addWidget(self.tbl, stretch=1)

        # 底部: 并排可视化 (查询 vs 选中条目)
        self.canvas = EEMCanvas()
        layout.addWidget(self.canvas, stretch=2)

        self.tbl.itemSelectionChanged.connect(self._show_pair)

        self._results = []   # cached search results

    def _search(self):
        lib = self._get_lib()
        if lib is None:
            QtWidgets.QMessageBox.warning(
                self, "无库", "请先在 [指纹库] 页面打开/新建库.")
            return
        ctx = self._get_current()
        if ctx is None:
            QtWidgets.QMessageBox.warning(
                self, "无样本", "请先在 [分析] 页面运行一次预处理.")
            return
        fp, raw, corr, blank_path, sample_path = ctx
        results = lib.search(
            fp.feature_vector,
            top_k=self.spn_topk.value(),
            cosine_weight=self.spn_w_cos.value(),
            euclid_weight=self.spn_w_eu.value(),
        )
        self._results = results
        self.tbl.setRowCount(len(results))
        for r, (entry, m) in enumerate(results):
            self.tbl.setItem(r, 0, QtWidgets.QTableWidgetItem(str(r + 1)))
            self.tbl.setItem(r, 1, QtWidgets.QTableWidgetItem(str(entry.id)))
            self.tbl.setItem(r, 2, QtWidgets.QTableWidgetItem(entry.name))
            self.tbl.setItem(r, 3, QtWidgets.QTableWidgetItem(entry.category))
            self.tbl.setItem(r, 4, QtWidgets.QTableWidgetItem(
                f"{m['cosine_similarity']:.4f}"))
            self.tbl.setItem(r, 5, QtWidgets.QTableWidgetItem(
                f"{m['euclidean_distance']:.4f}"))

    def _compare_with_top(self, row, col):
        self._show_pair()

    def _show_pair(self):
        rows = sorted({i.row() for i in self.tbl.selectedItems()})
        if not rows or not self._results:
            return
        r = rows[0]
        entry, _ = self._results[r]
        ctx = self._get_current()
        if ctx is None:
            return
        fp, raw, corr, blank_path, sample_path = ctx
        # 重建 entry 的 EEM
        if entry.feature_vector.size == entry.ex.size * entry.em.size:
            Me = entry.feature_vector.reshape(entry.ex.size, entry.em.size)
        else:
            Me = np.zeros((entry.ex.size, entry.em.size))
        self.canvas.plot_compare(
            corr.ex, corr.em, corr.intensity / max(corr.intensity.max(), 1e-9),
            f"Query: {os.path.basename(sample_path or '')}",
            entry.ex, entry.em, Me,
            f"#{entry.id} {entry.name}")


# =============================================================================
# Tab 5: 双样本比对
# =============================================================================
class CompareTab(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.proc = EEMProcessor()
        self.fp_a: Optional[Fingerprint] = None
        self.fp_b: Optional[Fingerprint] = None
        self.eem_a: Optional[EEM] = None
        self.eem_b: Optional[EEM] = None
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()

        def make_panel(label):
            box = QtWidgets.QGroupBox(label)
            vb = QtWidgets.QVBoxLayout(box)
            lbl_b = QtWidgets.QLabel("空白: (未选)")
            lbl_s = QtWidgets.QLabel("样本: (未选)")
            btn_b = QtWidgets.QPushButton("选择空白")
            btn_s = QtWidgets.QPushButton("选择样本")
            for w in (btn_b, lbl_b, btn_s, lbl_s):
                vb.addWidget(w)
            return box, btn_b, lbl_b, btn_s, lbl_s

        self.gb_a, b_ba, self.lbl_a_b, b_sa, self.lbl_a_s = make_panel("样本 A")
        self.gb_b, b_bb, self.lbl_b_b, b_sb, self.lbl_b_s = make_panel("样本 B")
        top.addWidget(self.gb_a)
        top.addWidget(self.gb_b)
        layout.addLayout(top)

        self.paths = {"a_blank": None, "a_sample": None,
                      "b_blank": None, "b_sample": None}
        b_ba.clicked.connect(lambda: self._pick("a_blank", self.lbl_a_b))
        b_sa.clicked.connect(lambda: self._pick("a_sample", self.lbl_a_s))
        b_bb.clicked.connect(lambda: self._pick("b_blank", self.lbl_b_b))
        b_sb.clicked.connect(lambda: self._pick("b_sample", self.lbl_b_s))

        btn = QtWidgets.QPushButton("▶ 计算两样本相似度 (余弦 + 欧式)")
        btn.setStyleSheet(
            "QPushButton{padding:8px;background:#C44E52;color:white;font-weight:bold;border-radius:4px;}")
        btn.clicked.connect(self._run)
        layout.addWidget(btn)

        # 结果框
        self.lbl_result = QtWidgets.QLabel("(等待运行)")
        self.lbl_result.setStyleSheet(
            "padding:8px;background:#f0f0f0;border:1px solid #ccc;font-family:monospace;")
        self.lbl_result.setAlignment(QtCore.Qt.AlignTop)
        layout.addWidget(self.lbl_result)

        # 并排可视化
        self.canvas = EEMCanvas()
        layout.addWidget(self.canvas, stretch=1)

    def _pick(self, key, label):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择 CSV", "", "CSV (*.csv)")
        if path:
            self.paths[key] = path
            label.setText(os.path.basename(path))

    def _run(self):
        try:
            for k in self.paths:
                if not self.paths[k]:
                    QtWidgets.QMessageBox.warning(
                        self, "缺文件", "请为 A、B 两组都选好 blank 与 sample.")
                    return
            ba = self.proc.load_and_aggregate(self.paths["a_blank"])
            sa = self.proc.load_and_aggregate(self.paths["a_sample"])
            ca = self.proc.correct(sa, ba)
            fa = extract_fingerprint(ca)

            bb = self.proc.load_and_aggregate(self.paths["b_blank"])
            sb = self.proc.load_and_aggregate(self.paths["b_sample"])
            cb = self.proc.correct(sb, bb)
            fb = extract_fingerprint(cb)

            n = min(fa.feature_vector.size, fb.feature_vector.size)
            va = fa.feature_vector[:n].astype(np.float64)
            vb = fb.feature_vector[:n].astype(np.float64)
            na = np.linalg.norm(va) or 1e-12
            nbn = np.linalg.norm(vb) or 1e-12
            cos = float(np.dot(va, vb) / (na * nbn))
            eucl = float(np.linalg.norm(va / na - vb / nbn))
            score = 0.6 * max(cos, 0) + 0.4 * max(0, 1 - eucl / 2)

            self.lbl_result.setText(
                f"  余弦相似度  (Cosine Similarity)   : {cos:.4f}\n"
                f"  归一化欧式距离 (Euclidean)         : {eucl:.4f}\n"
                f"  综合相似度评分 (0.6·cos + 0.4·eucl_sim) : {score:.4f}\n")

            self.canvas.plot_compare(
                ca.ex, ca.em, ca.intensity, "Sample A",
                cb.ex, cb.em, cb.intensity, "Sample B")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "比对失败", f"{e}\n{traceback.format_exc()}")


# =============================================================================
# 主窗口
# =============================================================================
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 820)

        self.tab_analysis = AnalysisTab()
        self.tab_lib = LibraryTab(self._current_fingerprint_ctx)
        self.tab_search = SearchTab(
            self._current_fingerprint_ctx,
            lambda: self.tab_lib.lib)
        self.tab_compare = CompareTab()

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self.tab_analysis, "1. 数据加载与预处理")
        tabs.addTab(self.tab_lib, "2. 指纹库管理")
        tabs.addTab(self.tab_search, "3. 指纹检索")
        tabs.addTab(self.tab_compare, "4. 双样本比对")
        self.setCentralWidget(tabs)

        # 状态栏
        self.statusBar().showMessage("就绪 | 请先加载 EEM 空白与样本文件")

        # ---- 主菜单 -------------------------------------------------------
        m_file = self.menuBar().addMenu("文件(&F)")
        act_load_blank = QtWidgets.QAction("加载空白 EEM…(&B)", self)
        act_load_blank.setShortcut("Ctrl+B")
        act_load_blank.triggered.connect(self.tab_analysis._pick_blank)
        m_file.addAction(act_load_blank)
        act_load_sample = QtWidgets.QAction("加载样本 EEM…(&S)", self)
        act_load_sample.setShortcut("Ctrl+L")
        act_load_sample.triggered.connect(self.tab_analysis._pick_sample)
        m_file.addAction(act_load_sample)
        act_run = QtWidgets.QAction("运行预处理 + 特征提取(&R)", self)
        act_run.setShortcut("F5")
        act_run.triggered.connect(self.tab_analysis._run)
        m_file.addAction(act_run)
        m_file.addSeparator()
        act_quit = QtWidgets.QAction("退出(&Q)", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)
        m_help = self.menuBar().addMenu("帮助(&H)")
        act_about = QtWidgets.QAction("关于…", self)
        act_about.triggered.connect(self._about)
        m_help.addAction(act_about)

    def _current_fingerprint_ctx(self):
        """提供当前样本上下文给其他 Tab. 返回 None 表示尚未运行."""
        if self.tab_analysis.current_fp is None:
            return None
        return (self.tab_analysis.current_fp,
                self.tab_analysis.current_raw,
                self.tab_analysis.current_corr,
                self.tab_analysis.blank_path,
                self.tab_analysis.sample_path)

    def _about(self):
        QtWidgets.QMessageBox.information(
            self, "关于",
            f"<b>{APP_TITLE}</b><br><br>"
            "基于纯水 EEM 空白扣减、瑞利/拉曼散射屏蔽、SG 平滑的水质三维荧光光谱指纹工具.<br>"
            "支持 EEM 预处理 / 指纹特征提取 / SQLite 指纹库 / 检索 / 双样本比对.<br>"
            "相似度算法: 余弦相似度 + 归一化欧式距离."
        )

    def closeEvent(self, ev):
        if self.tab_lib.lib is not None:
            self.tab_lib.lib.close()
        super().closeEvent(ev)


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
