"""Renders a MomentumEngine result as a FIFA-broadcast-style momentum chart.

Takes chart structure (axis ticks, interval markers) from a Sport's
ChartProfile rather than hardcoding any one sport's match structure.
"""

import matplotlib.pyplot as plt

BG_PANEL = "#3d4147"
BG_FIG = "#23262b"
GOAL_LINE = "#e8e8e8"


def _draw_score_markers(ax, events, home):
    """Goal-line markers, staggering labels that fall within 12 min of each other."""
    last_x = {1: -100, -1: -100}
    high = {1: False, -1: False}
    for ev in events:
        if ev.marker != "score":
            continue
        sign = 1 if ev.team == home else -1
        high[sign] = not high[sign] if ev.t - last_x[sign] < 12 else False
        last_x[sign] = ev.t
        tip = 1.12 + (0.14 if high[sign] else 0)
        ax.plot([ev.t, ev.t], [0, sign * tip], color=GOAL_LINE, lw=1.4)
        ax.plot(ev.t, sign * tip, marker="o", ms=9, mfc="white", mec="#555", zorder=5)
        ax.annotate(ev.label or "", (ev.t, sign * (tip + 0.12)),
                    ha="center", va="center", fontsize=8.5,
                    color="#f0f0f0", fontweight="bold")


def _draw_note_markers(ax, events, home):
    """Secondary annotation markers (e.g. missed penalty, sin bin)."""
    for ev in events:
        if ev.marker != "note":
            continue
        sign = 1 if ev.team == home else -1
        ax.plot(ev.t, sign * 1.12, marker="x", ms=9, mew=2.5,
                color="#f5c518", zorder=5)
        ax.annotate(ev.label or "", (ev.t, sign * 1.24),
                    ha="center", va="center", fontsize=8.5,
                    color="#f5c518", fontweight="bold")


def _style_axes(fig, ax, chart_profile, home, away, home_color, away_color,
                title, footer):
    ax.set_xlim(0, chart_profile.max_t)
    ax.set_ylim(-1.55, 1.55)
    ax.set_xticks(chart_profile.tick_positions)
    ax.set_xticklabels(chart_profile.tick_labels,
                        color="#e0e0e0", fontsize=11, fontweight="bold")
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)

    ax.set_title(title, color="white", fontsize=15, fontweight="bold", pad=18)
    ax.text(0.012, 0.96, home, transform=ax.transAxes, color=home_color,
            fontsize=13, fontweight="bold", va="top")
    ax.text(0.012, 0.04, away, transform=ax.transAxes, color=away_color,
            fontsize=13, fontweight="bold", va="bottom")
    fig.text(0.5, 0.015, footer or "", ha="center", color="#9a9a9a", fontsize=8)


def render(t, y_home, y_away, events, home, away, chart_profile,
           home_color, away_color, title, footer, out_path):
    fig, ax = plt.subplots(figsize=(12, 5.2), dpi=200)
    fig.patch.set_facecolor(BG_FIG)
    ax.set_facecolor(BG_PANEL)

    # net momentum: one side at a time, FIFA-broadcast style
    ax.fill_between(t, 0, y_home, color=home_color, alpha=0.95, lw=0)
    ax.fill_between(t, 0, -y_away, color=away_color, alpha=0.95, lw=0)
    ax.axhline(0, color="#d9d9d9", lw=2)

    for m in chart_profile.interval_markers:
        ax.axvline(m, color="#c8c8c8", lw=1.2, alpha=0.7)

    _draw_score_markers(ax, events, home)
    _draw_note_markers(ax, events, home)
    _style_axes(fig, ax, chart_profile, home, away, home_color, away_color,
                title, footer)

    plt.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(out_path, facecolor=BG_FIG, bbox_inches="tight")
