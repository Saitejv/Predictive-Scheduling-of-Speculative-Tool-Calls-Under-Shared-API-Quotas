"""Plot live pilot blocks; dots show block variation, not a confidence interval."""

import argparse
import json
from pathlib import Path
from statistics import mean

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def plot(root):
    runs = json.loads((root / "progress.json").read_text())["runs"]
    settings = sorted({(r["capacity"], r["window_s"]) for r in runs})
    policies = ["no_speculation", "allow_all", "jev", "blind", "quota"]
    labels = ["No spec.", "Allow all", "Jev", "Blind", "Quota"]
    fig, axes = plt.subplots(
        2,
        len(settings),
        figsize=(5 * len(settings), 8),
        squeeze=False,
        sharey="row",
        layout="constrained",
    )
    for column, (capacity, window) in enumerate(settings):
        for row, metric in enumerate(["mean_completion_s", "resource_makespan_s"]):
            ax = axes[row, column]
            for x, policy in enumerate(policies):
                values = [
                    r["summary"][metric]
                    for r in runs
                    if (r["capacity"], r["window_s"], r["policy"]) == (capacity, window, policy)
                ]
                if values:
                    ax.bar(
                        x,
                        mean(values),
                        color=["#8a9299", "#e7a04c", "#4382bb", "#a783bd", "#4b9d83"][x],
                        width=0.7,
                    )
                    ax.scatter([x] * len(values), values, s=22, c="black", zorder=3)
                    ax.text(x, max(values) + 0.3, f"{mean(values):.2f}", ha="center", fontsize=9)
            ax.set_xticks(range(5), labels, rotation=25)
            ax.spines[["top", "right"]].set_visible(False)
            ax.grid(axis="y", alpha=0.2)
            ax.set_axisbelow(True)
            if row == 0:
                ax.set_title(f"{capacity} Search calls / {window:g} seconds", fontweight="bold")
            if column == 0:
                ax.set_ylabel(
                    "Mean task completion (s)"
                    if row == 0
                    else "Mean 8-task batch resource time (s)"
                )
    fig.suptitle(
        "Direct quota-aware speculation vs controls — exploratory live pilot\n"
        "4 workers; autonomous model paths; black dots = individual blocks; lower is better",
        fontweight="bold",
    )
    fig.savefig(root / "live-comparison.png", dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    plot(p.parse_args().source)
