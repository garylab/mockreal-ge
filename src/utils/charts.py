"""Generate publication-quality data visualizations for article images.

Style: dark-themed, clean, minimal — inspired by The Economist / Bloomberg.
Never basic matplotlib defaults.
"""
from __future__ import annotations

import io
import uuid
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import seaborn as sns
from loguru import logger as log

from src.storage.r2_client import upload_image

# ── Global style ──────────────────────────────────────────────

_BG = "#0f1117"
_FG = "#e0e0e0"
_ACCENT = "#6c5ce7"
_ACCENT2 = "#00cec9"
_ACCENT3 = "#fd79a8"
_GRID = "#1e2130"
_PALETTE = [_ACCENT, _ACCENT2, _ACCENT3, "#ffeaa7", "#74b9ff", "#a29bfe"]

sns.set_theme(style="darkgrid", rc={
    "figure.facecolor": _BG,
    "axes.facecolor": _BG,
    "axes.edgecolor": _GRID,
    "axes.labelcolor": _FG,
    "axes.grid": True,
    "grid.color": _GRID,
    "grid.linestyle": "--",
    "grid.alpha": 0.4,
    "text.color": _FG,
    "xtick.color": _FG,
    "ytick.color": _FG,
    "font.family": "sans-serif",
    "font.size": 12,
    "axes.titlesize": 16,
    "axes.labelsize": 13,
})


def _finalize(fig: plt.Figure, title: str) -> bytes:
    fig.tight_layout(pad=1.5)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _upload(img_bytes: bytes, prefix: str) -> str:
    filename = f"{prefix}-{uuid.uuid4().hex[:8]}.png"
    return upload_image(img_bytes, filename)


# ── Chart types ───────────────────────────────────────────────

def trend_line(
    labels: list[str],
    values: list[float],
    title: str = "",
    ylabel: str = "",
    highlight_last: bool = True,
) -> str | None:
    """Line chart for time-series / trend data. Returns R2 URL."""
    try:
        fig, ax = plt.subplots(figsize=(10, 5))
        x = range(len(labels))

        ax.plot(x, values, color=_ACCENT, linewidth=2.5, marker="o",
                markersize=6, markerfacecolor=_ACCENT2, markeredgecolor=_ACCENT2,
                zorder=3)
        ax.fill_between(x, values, alpha=0.08, color=_ACCENT)

        if highlight_last and values:
            ax.annotate(
                f"{values[-1]:.0f}", xy=(len(values) - 1, values[-1]),
                xytext=(10, 10), textcoords="offset points",
                fontsize=14, fontweight="bold", color=_ACCENT2,
                arrowprops=dict(arrowstyle="->", color=_ACCENT2, lw=1.5),
            )

        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=10)
        ax.set_ylabel(ylabel, fontsize=12)
        if title:
            ax.set_title(title, fontsize=16, fontweight="bold", pad=12)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        return _upload(_finalize(fig, title), "chart-trend")
    except Exception as exc:
        log.debug("trend_line chart failed: {}", exc)
        return None


def comparison_bar(
    categories: list[str],
    values: list[float],
    title: str = "",
    ylabel: str = "",
    horizontal: bool = False,
) -> str | None:
    """Horizontal or vertical bar chart for comparisons. Returns R2 URL."""
    try:
        fig, ax = plt.subplots(figsize=(10, max(5, len(categories) * 0.6)))
        colors = [_PALETTE[i % len(_PALETTE)] for i in range(len(categories))]

        if horizontal:
            bars = ax.barh(categories, values, color=colors, height=0.6,
                           edgecolor="none", zorder=3)
            for bar, val in zip(bars, values):
                ax.text(bar.get_width() + max(values) * 0.02,
                        bar.get_y() + bar.get_height() / 2,
                        f"{val:,.0f}", va="center", fontsize=11,
                        fontweight="bold", color=_FG)
            ax.set_xlabel(ylabel)
            ax.invert_yaxis()
        else:
            bars = ax.bar(categories, values, color=colors, width=0.6,
                          edgecolor="none", zorder=3)
            for bar, val in zip(bars, values):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                        f"{val:,.0f}", ha="center", va="bottom",
                        fontsize=11, fontweight="bold", color=_FG)
            ax.set_ylabel(ylabel)

        if title:
            ax.set_title(title, fontsize=16, fontweight="bold", pad=12)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        return _upload(_finalize(fig, title), "chart-bar")
    except Exception as exc:
        log.debug("comparison_bar chart failed: {}", exc)
        return None


def donut(
    labels: list[str],
    values: list[float],
    title: str = "",
) -> str | None:
    """Donut chart for proportions / market share. Returns R2 URL."""
    try:
        fig, ax = plt.subplots(figsize=(8, 8))
        colors = [_PALETTE[i % len(_PALETTE)] for i in range(len(labels))]

        wedges, texts, autotexts = ax.pie(
            values, labels=labels, colors=colors, autopct="%1.0f%%",
            startangle=140, pctdistance=0.78, wedgeprops=dict(width=0.4, edgecolor=_BG),
            textprops={"color": _FG, "fontsize": 12},
        )
        for at in autotexts:
            at.set_fontsize(11)
            at.set_fontweight("bold")
            at.set_color(_FG)

        if title:
            ax.set_title(title, fontsize=16, fontweight="bold", pad=20)

        return _upload(_finalize(fig, title), "chart-donut")
    except Exception as exc:
        log.debug("donut chart failed: {}", exc)
        return None


def stat_highlight(
    stats: list[dict[str, Any]],
    title: str = "",
) -> str | None:
    """Big-number stat cards (like a dashboard KPI row).
    stats: [{"label": "...", "value": "85%", "subtitle": "..."}, ...]
    Returns R2 URL.
    """
    try:
        n = len(stats)
        fig, axes = plt.subplots(1, n, figsize=(4 * n, 3))
        if n == 1:
            axes = [axes]

        for ax, stat, color in zip(axes, stats, _PALETTE):
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")

            ax.add_patch(plt.Rectangle(
                (0.05, 0.05), 0.9, 0.9, facecolor=_GRID,
                edgecolor=color, linewidth=2, alpha=0.7, transform=ax.transAxes,
            ))
            ax.text(0.5, 0.62, str(stat.get("value", "")),
                    ha="center", va="center", fontsize=36, fontweight="bold",
                    color=color, transform=ax.transAxes)
            ax.text(0.5, 0.32, stat.get("label", ""),
                    ha="center", va="center", fontsize=13,
                    color=_FG, transform=ax.transAxes)
            if stat.get("subtitle"):
                ax.text(0.5, 0.15, stat["subtitle"],
                        ha="center", va="center", fontsize=10,
                        color=_FG, alpha=0.6, transform=ax.transAxes)

        if title:
            fig.suptitle(title, fontsize=16, fontweight="bold",
                         color=_FG, y=1.02)

        return _upload(_finalize(fig, title), "chart-stats")
    except Exception as exc:
        log.debug("stat_highlight chart failed: {}", exc)
        return None
