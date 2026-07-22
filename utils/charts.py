import os
import matplotlib
matplotlib.use("Agg")
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.ticker import MaxNLocator, FuncFormatter

from database.db import get_connection


def _smooth_curve(x, y, samples_per_segment=30):
    """Catmull-Rom interpolation that still passes exactly through every point."""

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)

    if n < 3:
        return x, y

    xp = np.concatenate(([x[0]], x, [x[-1]]))
    yp = np.concatenate(([y[0]], y, [y[-1]]))

    out_x, out_y = [], []

    for i in range(1, n):
        p0x, p1x, p2x, p3x = xp[i - 1], xp[i], xp[i + 1], xp[i + 2]
        p0y, p1y, p2y, p3y = yp[i - 1], yp[i], yp[i + 1], yp[i + 2]

        t = np.linspace(0, 1, samples_per_segment, endpoint=(i == n - 1))
        t2 = t * t
        t3 = t2 * t

        seg_x = 0.5 * (2 * p1x + (-p0x + p2x) * t +
                        (2 * p0x - 5 * p1x + 4 * p2x - p3x) * t2 +
                        (-p0x + 3 * p1x - 3 * p2x + p3x) * t3)
        seg_y = 0.5 * (2 * p1y + (-p0y + p2y) * t +
                        (2 * p0y - 5 * p1y + 4 * p2y - p3y) * t2 +
                        (-p0y + 3 * p1y - 3 * p2y + p3y) * t3)

        out_x.append(seg_x)
        out_y.append(seg_y)

    return np.concatenate(out_x), np.concatenate(out_y)


def _format_currency_short(value, _pos=None):
    """Compact axis labels: 850 -> Rs.850, 1000 -> Rs.1K, 12500 -> Rs.12.5K"""

    value = round(value)

    if abs(value) >= 1000:
        thousands = value / 1000
        if thousands == int(thousands):
            return f"₹{int(thousands)}K"
        return f"₹{thousands:.1f}K"

    return f"₹{int(value)}"


def generate_revenue_chart(admin_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""

        SELECT

            strftime('%m', p.payment_date) AS month,

            IFNULL(SUM(p.amount_paid),0) AS revenue

        FROM payments p

        JOIN students s

            ON p.student_id = s.student_id

        WHERE s.admin_id = ?

            AND strftime('%Y', p.payment_date) = strftime('%Y', 'now')

        GROUP BY month

        ORDER BY month

    """, (admin_id,))

    data = cursor.fetchall()

    conn.close()

    months = [
        "Jan","Feb","Mar","Apr",
        "May","Jun","Jul","Aug",
        "Sep","Oct","Nov","Dec"
    ]

    revenue = [0] * 12

    for row in data:

        month_index = int(row["month"]) - 1

        revenue[month_index] = row["revenue"]

    line_color = "#2563eb"
    x_idx = np.arange(12)

    smooth_x, smooth_y = _smooth_curve(x_idx, revenue)
    smooth_y = np.clip(smooth_y, 0, None)

    peak = max(max(revenue), 5)

    fig, ax = plt.subplots(figsize=(9.6, 2.3), dpi=150)

    # Semi-transparent gradient fill under the curve
    gradient = np.empty((100, 1, 4), dtype=float)
    gradient[:, :, :3] = mcolors.to_rgb(line_color)
    gradient[:, :, 3] = np.linspace(0.28, 0.0, 100)[:, None]

    gradient_img = ax.imshow(
        gradient,
        aspect="auto",
        extent=[x_idx[0], x_idx[-1], 0, peak * 1.2],
        origin="upper",
        zorder=1
    )

    fill_region = ax.fill_between(smooth_x, 0, smooth_y, alpha=0)
    gradient_img.set_clip_path(fill_region.get_paths()[0], transform=ax.transData)

    # Smooth curved line
    ax.plot(
        smooth_x,
        smooth_y,
        color=line_color,
        linewidth=3,
        solid_capstyle="round",
        solid_joinstyle="round",
        zorder=3
    )

    # Small circular data points at the real values
    ax.plot(
        x_idx,
        revenue,
        linestyle="None",
        marker="o",
        markersize=5.5,
        markerfacecolor="#ffffff",
        markeredgecolor=line_color,
        markeredgewidth=1.8,
        zorder=4
    )

    ax.set_xticks(x_idx)
    ax.set_xticklabels(months)

    ax.yaxis.set_major_locator(MaxNLocator(nbins=4, integer=True, min_n_ticks=3))
    ax.yaxis.set_major_formatter(FuncFormatter(_format_currency_short))

    ax.tick_params(axis="x", labelsize=9.5, colors="#94a3b8", length=0, pad=8)
    ax.tick_params(axis="y", labelsize=9.5, colors="#94a3b8", length=0, pad=6)

    ax.grid(axis="y", color="#F1F5F9", linewidth=1.0)
    ax.set_axisbelow(True)

    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.set_xlim(x_idx[0], x_idx[-1])
    ax.set_ylim(bottom=0, top=peak * 1.2)

    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")

    chart_path = os.path.join(
        "static",
        "charts",
        "revenue.png"
    )

    fig.tight_layout(pad=0.4)

    fig.savefig(
        chart_path,
        bbox_inches="tight",
        pad_inches=0.08,
        facecolor="#ffffff"
    )

    plt.close(fig)


# ==========================================
# Membership Distribution Pie Chart
# ==========================================

def generate_membership_chart(admin_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            m.plan_name,
            COUNT(*) AS total

        FROM memberships m

        JOIN students s
            ON s.student_id = m.student_id

        WHERE
            s.admin_id = ?

        GROUP BY
            m.plan_name

        ORDER BY
            total DESC
    """, (admin_id,))

    data = cursor.fetchall()

    conn.close()

    labels = []
    sizes = []

    for row in data:

        labels.append(row["plan_name"])
        sizes.append(row["total"])

    fig, ax = plt.subplots(figsize=(3.6, 3.6), dpi=180)

    if not sizes:

        # See generate_membership_distribution_donut()'s identical fix for
        # why explicit symmetric limits are needed before placing (0, 0)
        # text with bbox_inches="tight" - otherwise it crops to the
        # bottom-left corner instead of centering.
        ax.set_xlim(-1, 1)
        ax.set_ylim(-1, 1)
        ax.text(
            0, 0, "No membership\ndata yet",
            ha="center", va="center",
            fontsize=11, color="#94a3b8"
        )
        ax.axis("off")

        chart_path = os.path.join("static", "charts", "membership.png")

        fig.savefig(
            chart_path,
            dpi=180,
            bbox_inches="tight",
            pad_inches=0.15,
            facecolor="#ffffff"
        )

        plt.close(fig)
        return

    wedges, _texts, autotexts = ax.pie(
        sizes,
        autopct="%1.0f%%",
        startangle=90,
        pctdistance=0.7,
        radius=0.78,
        explode=[0.03] * len(sizes),
        wedgeprops={"linewidth": 1.5, "edgecolor": "#ffffff"},
        textprops={"fontsize": 9, "fontweight": "bold", "color": "#ffffff"}
    )

    for autotext in autotexts:
        autotext.set_fontsize(9)
        autotext.set_fontweight("bold")
        autotext.set_color("#ffffff")

    # Category labels sit outside the pie, connected by a thin leader line,
    # with a simple per-side de-overlap pass since matplotlib doesn't do this itself.
    label_points = []

    for wedge in wedges:
        angle = np.deg2rad((wedge.theta2 + wedge.theta1) / 2)
        label_points.append({
            "x": np.cos(angle),
            "y": np.sin(angle),
            "target_y": np.sin(angle),
        })

    min_gap = 0.24

    for side in ("right", "left"):
        side_points = [
            p for p in label_points
            if (p["x"] >= 0) == (side == "right")
        ]
        side_points.sort(key=lambda p: p["target_y"], reverse=True)

        for i in range(1, len(side_points)):
            if side_points[i - 1]["target_y"] - side_points[i]["target_y"] < min_gap:
                side_points[i]["target_y"] = side_points[i - 1]["target_y"] - min_gap

    bbox_props = dict(boxstyle="round,pad=0.28", fc="#ffffff", ec="#e2e8f0", lw=1)

    for i, wedge in enumerate(wedges):
        point = label_points[i]
        is_right = point["x"] >= 0
        leader_x = 0.86 * point["x"]
        leader_y = 0.86 * point["y"]
        label_x = 1.12 if is_right else -1.12

        ax.annotate(
            labels[i],
            xy=(leader_x, leader_y),
            xytext=(label_x, point["target_y"]),
            ha="left" if is_right else "right",
            va="center",
            fontsize=8.5,
            color="#4b5563",
            bbox=bbox_props,
            arrowprops=dict(
                arrowstyle="-",
                color="#cbd5e1",
                lw=1,
                connectionstyle=f"angle,angleA=0,angleB={np.degrees(np.arctan2(point['y'], point['x']))}"
            ),
            zorder=5
        )

    # Fit the axes box to the labels' real vertical spread instead of the
    # default square data range, so bbox_inches="tight" doesn't leave the
    # empty top/bottom margin a fixed -1.25..1.25 box would produce.
    label_ys = [p["target_y"] for p in label_points] + [-0.78, 0.78]
    y_pad = 0.22
    ax.set_xlim(-1.55, 1.55)
    ax.set_ylim(min(label_ys) - y_pad, max(label_ys) + y_pad)
    ax.set_aspect("equal", adjustable="box")

    chart_path = os.path.join(
        "static",
        "charts",
        "membership.png"
    )

    fig.tight_layout(pad=0.3)

    fig.savefig(
        chart_path,
        dpi=180,
        bbox_inches="tight",
        pad_inches=0.15,
        facecolor="#ffffff"
    )

    plt.close(fig)


# ==========================================================
# Membership Distribution Donut Chart
# (larger version for the Membership Distribution Details page)
# ==========================================================

PLAN_CHART_COLORS = {
    "Monthly": "#2563eb",
    "Quarterly": "#06b6d4",
    "Half-Yearly": "#f59e0b",
    "Yearly": "#7c3aed",
}
PLAN_CHART_FALLBACK_COLOR = "#94a3b8"


def generate_membership_distribution_donut(admin_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            m.plan_name,
            COUNT(*) AS total

        FROM memberships m

        JOIN students s
            ON s.student_id = m.student_id

        WHERE
            s.admin_id = ?

        GROUP BY
            m.plan_name

        ORDER BY
            total DESC
    """, (admin_id,))

    data = cursor.fetchall()

    conn.close()

    labels = [row["plan_name"] for row in data]
    sizes = [row["total"] for row in data]
    total = sum(sizes)

    fig, ax = plt.subplots(figsize=(5.4, 5.4), dpi=170)

    if not sizes:
        # Explicit symmetric limits so (0, 0) is the actual center of the
        # cropped image - without this, bbox_inches="tight" crops to the
        # text's own bounding box against matplotlib's default (0, 1) axes
        # extent, leaving the text pinned in the bottom-left corner instead
        # of centered.
        ax.set_xlim(-1, 1)
        ax.set_ylim(-1, 1)
        ax.text(
            0, 0, "No membership\ndata yet",
            ha="center", va="center",
            fontsize=13, color="#94a3b8"
        )
        ax.axis("off")

    else:
        colors = [
            PLAN_CHART_COLORS.get(label, PLAN_CHART_FALLBACK_COLOR)
            for label in labels
        ]

        # Slightly smaller than a full unit circle so the wedge, its leader
        # lines and labels all sit comfortably inside the saved figure.
        radius = 0.95

        wedges, _texts, autotexts = ax.pie(
            sizes,
            colors=colors,
            autopct="%1.0f%%",
            startangle=90,
            pctdistance=0.82,
            radius=radius,
            explode=[0.02] * len(sizes),
            wedgeprops={"linewidth": 2, "edgecolor": "#ffffff", "width": 0.46},
            textprops={"fontsize": 10, "fontweight": "bold", "color": "#ffffff"}
        )

        for autotext in autotexts:
            autotext.set_fontsize(10)
            autotext.set_fontweight("bold")
            autotext.set_color("#ffffff")

        # Center total label sitting in the donut hole, offset symmetrically
        # around y=0 so the two-line block reads as vertically centered.
        ax.text(
            0, 0.08, f"{total}",
            ha="center", va="center",
            fontsize=32, fontweight="bold", color="#1a2234"
        )
        ax.text(
            0, -0.14, "Total Memberships",
            ha="center", va="center",
            fontsize=10, color="#94a3b8"
        )

        # External labels connected by leader lines, de-overlapped per side
        # the same way the compact dashboard pie chart does.
        label_points = []

        for wedge in wedges:
            angle = np.deg2rad((wedge.theta2 + wedge.theta1) / 2)
            label_points.append({
                "x": radius * np.cos(angle),
                "y": radius * np.sin(angle),
                "target_y": radius * np.sin(angle),
            })

        min_gap = 0.22

        for side in ("right", "left"):
            side_points = [
                p for p in label_points
                if (p["x"] >= 0) == (side == "right")
            ]
            side_points.sort(key=lambda p: p["target_y"], reverse=True)

            for i in range(1, len(side_points)):
                if side_points[i - 1]["target_y"] - side_points[i]["target_y"] < min_gap:
                    side_points[i]["target_y"] = side_points[i - 1]["target_y"] - min_gap

        bbox_props = dict(boxstyle="round,pad=0.3", fc="#ffffff", ec="#e2e8f0", lw=1)

        for i, wedge in enumerate(wedges):
            point = label_points[i]
            is_right = point["x"] >= 0
            leader_x = 1.06 * point["x"]
            leader_y = 1.06 * point["y"]
            label_x = 1.34 if is_right else -1.34

            ax.annotate(
                f"{labels[i]}  ({sizes[i]})",
                xy=(leader_x, leader_y),
                xytext=(label_x, point["target_y"]),
                ha="left" if is_right else "right",
                va="center",
                fontsize=9.5,
                color="#4b5563",
                bbox=bbox_props,
                arrowprops=dict(
                    arrowstyle="-",
                    color="#cbd5e1",
                    lw=1,
                    connectionstyle=f"angle,angleA=0,angleB={np.degrees(np.arctan2(point['y'], point['x']))}"
                ),
                zorder=5
            )

        label_ys = [p["target_y"] for p in label_points] + [-radius, radius]
        y_pad = 0.26
        ax.set_xlim(-1.85, 1.85)
        ax.set_ylim(min(label_ys) - y_pad, max(label_ys) + y_pad)
        ax.set_aspect("equal", adjustable="box")

    chart_path = os.path.join(
        "static",
        "charts",
        "membership_distribution_donut.png"
    )

    fig.tight_layout(pad=0.2)

    fig.savefig(
        chart_path,
        dpi=170,
        bbox_inches="tight",
        pad_inches=0.18,
        facecolor="#ffffff"
    )

    plt.close(fig)
