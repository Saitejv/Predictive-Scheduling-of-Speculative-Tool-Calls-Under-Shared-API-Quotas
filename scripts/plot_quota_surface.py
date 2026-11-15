"""Plot measured quota surfaces, averaging all saved orders; no model calls."""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def plot(root, agents):
    rows = json.loads((root / "rows.json").read_text())
    capacities = sorted({r["capacity"] for r in rows})
    windows = sorted({r["window_s"] for r in rows})
    groups = defaultdict(list)
    for r in rows:
        groups[r["agents"], r["capacity"], r["window_s"], r["policy"]].append(r)
    by = {
        key: {
            metric: mean(r[metric] for r in group)
            for metric in ("mean_completion_s", "resource_makespan_s")
        }
        for key, group in groups.items()
    }
    fig, axs = plt.subplots(2, 2, figsize=(16, 11), layout="constrained")
    for i, (metric, base, title) in enumerate(
        [
            ("mean_completion_s", "none", "Mean task saving vs no speculation"),
            ("mean_completion_s", "all", "Mean task saving vs allow-all"),
            ("resource_makespan_s", "none", "Whole-batch time saving vs no speculation"),
            ("resource_makespan_s", "all", "Whole-batch time saving vs allow-all"),
        ]
    ):
        data = []
        for c in capacities:
            row = []
            for w in windows:
                method = by[agents, c, w, "cal"][metric]
                baseline = by[agents, c, w, base][metric]
                row.append(100 * (1 - method / baseline))
            data.append(row)
        values = np.array(data)
        ax = axs.flat[i]
        limit = max(5.0, float(np.nanmax(np.abs(values))))
        im = ax.imshow(
            values, origin="lower", aspect="auto", cmap="RdYlGn", vmin=-limit, vmax=limit
        )
        ax.set_xticks(range(len(windows)), [f"{w:g}" for w in windows])
        ax.set_yticks(range(len(capacities)), capacities)
        ax.set_xlabel("Quota refill period (seconds)")
        ax.set_ylabel("Search calls allowed per window")
        ax.set_title(title, loc="left", fontweight="bold")
        if agents == 4 and 12 in capacities and 3 in windows:
            from matplotlib.patches import Rectangle

            ax.add_patch(
                Rectangle(
                    (windows.index(3) - 0.48, capacities.index(12) - 0.48),
                    0.96,
                    0.96,
                    fill=False,
                    edgecolor="black",
                    linewidth=2.5,
                )
            )
        for y in range(len(capacities)):
            for x in range(len(windows)):
                ax.text(
                    x,
                    y,
                    f"{values[y, x]:+.1f}",
                    ha="center",
                    va="center",
                    fontsize=8,
                    color="black",
                    fontweight="bold" if values[y, x] > 0 else "normal",
                )
        fig.colorbar(im, ax=ax, label="Percent improvement; green is better")
    config_path = root / "config.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    scope = config.get("scope", "development")
    tasks = rows[0]["tasks"]
    seeds = len({r["seed"] for r in rows})
    label = (
        "Fixed-method exploratory held-out grid" if scope == "evaluation" else "DEVELOPMENT ONLY"
    )
    fig.suptitle(
        f"{label} — calibrated cross-agent Jev, {agents} workers\n"
        f"{tasks} questions; measured replay; means across {seeds} orders; black box = locked primary",
        fontweight="bold",
        fontsize=15,
    )
    fig.savefig(root / f"quota-surface-{agents}-workers.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("--agents", type=int, nargs="+", default=[2, 4, 8])
    args = p.parse_args()
    for count in args.agents:
        plot(args.source, count)
