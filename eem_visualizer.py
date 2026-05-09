# -*- coding: utf-8 -*-
"""
matplotlib 嵌入 PyQt5 的 EEM 可视化组件.
提供等高线图 / 伪彩图 / FRI 柱状图.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavToolbar

from PyQt5 import QtWidgets


# 让 matplotlib 显示中文 (常见思路: 优先 SimHei / Microsoft YaHei)
import matplotlib
matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei", "SimHei", "Arial Unicode MS",
    "WenQuanYi Zen Hei", "DejaVu Sans"
]
matplotlib.rcParams["axes.unicode_minus"] = False


class EEMCanvas(QtWidgets.QWidget):
    """带工具栏的可嵌入 EEM 绘图组件 (单图)."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.figure = Figure(figsize=(6, 4.5), tight_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavToolbar(self.canvas, self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        self._cbar = None

    # ---- EEM 绘制 ----------------------------------------------------------
    def _prepare_axes(self):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        return ax

    def plot_contour(self, ex: np.ndarray, em: np.ndarray, M: np.ndarray,
                     title: str = "EEM Contour", levels: int = 24,
                     cmap: str = "jet", fill: bool = True) -> None:
        """
        绘制等高线图.
            fill = True  → contourf 着色填充
            fill = False → contour 仅画等值线 (黑白线 + 数值标注)
        """
        ax = self._prepare_axes()
        M = np.nan_to_num(M, nan=0.0)
        if fill:
            cs = ax.contourf(em, ex, M, levels=levels, cmap=cmap)
            self.figure.colorbar(cs, ax=ax, label="Intensity (a.u.)")
        else:
            cs = ax.contour(em, ex, M, levels=levels,
                            colors="k", linewidths=0.7)
            ax.clabel(cs, inline=True, fontsize=7, fmt="%.0f")
        ax.set_xlabel("Emission λ / nm")
        ax.set_ylabel("Excitation λ / nm")
        ax.set_title(title)
        self.canvas.draw_idle()


    def plot_pcolor(self, ex: np.ndarray, em: np.ndarray, M: np.ndarray,
                    title: str = "EEM Pseudo-color",
                    cmap: str = "viridis") -> None:
        """绘制伪彩图 (pcolormesh)."""
        ax = self._prepare_axes()
        M = np.nan_to_num(M, nan=0.0)
        mesh = ax.pcolormesh(em, ex, M, cmap=cmap, shading="auto")
        ax.set_xlabel("Emission λ / nm")
        ax.set_ylabel("Excitation λ / nm")
        ax.set_title(title)
        self.figure.colorbar(mesh, ax=ax, label="Intensity (a.u.)")
        self.canvas.draw_idle()

    def plot_fri_bar(self, fractions: dict,
                     title: str = "FRI 五区域组成",
                     name_map: Optional[dict] = None) -> None:
        """绘制 FRI 五区比例柱状图. name_map: 英文 key → 中文标注."""
        ax = self._prepare_axes()
        keys = list(fractions.keys())
        labels = [name_map.get(k, k) if name_map else k for k in keys]
        vals = [fractions[k] for k in keys]
        colors = ["#4C72B0", "#55A868", "#C44E52", "#8172B2", "#CCB974"]
        bars = ax.bar(labels, vals, color=colors[:len(keys)])
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2,
                    b.get_height() + max(vals) * 0.01,
                    f"{v*100:.1f}%", ha="center", va="bottom", fontsize=8)
        ax.set_ylabel("占比")
        ax.set_ylim(0, max(1.0, max(vals) * 1.15) if vals else 1.0)
        ax.set_title(title)
        for tick in ax.get_xticklabels():
            tick.set_rotation(15)
            tick.set_ha("right")
            tick.set_fontsize(9)
        self.figure.subplots_adjust(bottom=0.22)
        self.canvas.draw_idle()

    def plot_compare(self, ex_a, em_a, M_a, label_a,
                     ex_b, em_b, M_b, label_b,
                     levels: int = 20, cmap: str = "jet") -> None:
        """并排显示两幅 EEM 等高线图."""
        self.figure.clear()
        ax1 = self.figure.add_subplot(121)
        ax2 = self.figure.add_subplot(122)
        Ma = np.nan_to_num(M_a, nan=0.0)
        Mb = np.nan_to_num(M_b, nan=0.0)
        vmax = max(Ma.max(), Mb.max())
        c1 = ax1.contourf(em_a, ex_a, Ma, levels=levels,
                          cmap=cmap, vmin=0, vmax=vmax)
        c2 = ax2.contourf(em_b, ex_b, Mb, levels=levels,
                          cmap=cmap, vmin=0, vmax=vmax)
        for ax, lab in [(ax1, label_a), (ax2, label_b)]:
            ax.set_xlabel("Emission λ / nm")
            ax.set_ylabel("Excitation λ / nm")
            ax.set_title(lab)
        self.figure.colorbar(c2, ax=[ax1, ax2], label="Intensity (a.u.)",
                             shrink=0.85)
        self.canvas.draw_idle()

    def clear(self):
        self.figure.clear()
        self.canvas.draw_idle()


class ContourPanel(QtWidgets.QWidget):
    """
    等高线视图组件: EEMCanvas + 右下角 "着色模式" 选项框.

    用法:
        panel = ContourPanel()
        panel.plot(ex, em, M, title="...")
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.canvas = EEMCanvas()
        self._last = None  # (ex, em, M, title, levels, cmap) 缓存

        # 右下角"着色模式"选项框
        self.cmb_mode = QtWidgets.QComboBox()
        self.cmb_mode.addItems(["填充着色", "仅等值线 (无着色)"])
        self.cmb_mode.setToolTip("选择等高线图是否进行颜色填充")
        self.cmb_mode.currentIndexChanged.connect(self._on_mode_changed)

        bottom = QtWidgets.QHBoxLayout()
        bottom.setContentsMargins(0, 2, 6, 2)
        bottom.addStretch(1)
        bottom.addWidget(QtWidgets.QLabel("着色模式:"))
        bottom.addWidget(self.cmb_mode)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.canvas, stretch=1)
        layout.addLayout(bottom)

    def plot(self, ex, em, M, title="EEM Contour",
             levels: int = 24, cmap: str = "jet"):
        self._last = (ex, em, M, title, levels, cmap)
        self._draw()

    def _on_mode_changed(self, _idx):
        if self._last is not None:
            self._draw()

    def _draw(self):
        ex, em, M, title, levels, cmap = self._last
        fill = self.cmb_mode.currentIndex() == 0
        self.canvas.plot_contour(ex, em, M, title=title,
                                 levels=levels, cmap=cmap, fill=fill)

    def clear(self):
        self.canvas.clear()
        self._last = None
