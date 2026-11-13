"""Keep observed live speedup separate from fixed-path service-time replay."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def main():
    audit = json.loads(
        (ROOT / "results/speculation-discrepancy-audit-2026-11-13/AUDIT.json").read_text()
    )
    original = audit["original_live_20"]["by_mode"]
    matched = audit["matched_unlimited_quota"]["all50"]
    later = audit["later_live_50"]
    scenarios = [
        (
            "Original live benchmark: 20 questions",
            ["Sequential live", "Speculative live"],
            [original["sequential"]["mean_s"], original["speculative"]["mean_s"]],
            "Observed 10.3% lower mean time.\nIndependent actor paths; uncertainty includes zero.",
        ),
        (
            "Fixed-path replay: 50 questions",
            ["Prefetch off", "Speculation"],
            [matched["no_prefetch_mean_s"], matched["speculative_mean_s"]],
            "1.7% lower mean time on identical paths.\nModel service times fixed; no Search quota wait.",
        ),
        (
            "Later live capture: 50 questions",
            ["Sequential capture", "Speculative capture"],
            [later["sequential"]["mean_s"], later["speculative"]["mean_s"]],
            "43 pairs used a 1.1 s model-submission interval.\nA 150 s actor outlier occurs in speculative mode.",
        ),
    ]
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
            "text.color": "#1D2939",
            "axes.labelcolor": "#344054",
            "xtick.color": "#475467",
            "ytick.color": "#1D2939",
        }
    )
    fig, axes = plt.subplots(3, 1, figsize=(12, 9.2))
    fig.subplots_adjust(left=0.245, right=0.96, top=0.84, bottom=0.14, hspace=0.85)
    for ax, (title, labels, values, note) in zip(axes, scenarios):
        bars = ax.barh([0, 1], values, height=0.57, color=["#667085", "#20857D"])
        ax.set_yticks([0, 1], labels)
        ax.invert_yaxis()
        ax.set_xlim(0, 14.7)
        ax.tick_params(axis="y", length=0, pad=9)
        ax.tick_params(axis="x", length=0)
        ax.set_axisbelow(True)
        ax.xaxis.grid(True, color="#E6E9EE", linewidth=0.8)
        ax.set_title(title, loc="left", fontsize=13, pad=13)
        for bar, value in zip(bars, values):
            ax.text(value + 0.12, bar.get_y() + bar.get_height() / 2, f"{value:.3f} s", va="center")
        ax.text(
            1,
            -0.4,
            note,
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=10,
            color="#475467",
        )
    fig.suptitle(
        "Why the earlier speedup and the replay chart differ",
        fontsize=20,
        x=0.055,
        ha="left",
        y=0.98,
    )
    fig.text(
        0.055,
        0.922,
        "The old chart compared frozen scheduling policies, not the original live baseline. Lower bars are faster.",
        fontsize=11,
        color="#475467",
    )
    fig.supxlabel("Mean question completion time (seconds)", y=0.035, fontsize=12)
    fig.text(
        0.055,
        0.008,
        "Each panel is a different protocol/cohort. These values cannot isolate a causal speculation effect across panels.",
        fontsize=10,
        color="#475467",
    )
    target = ROOT / "docs/figures/speculation-reconciliation.png"
    fig.savefig(target, dpi=170, facecolor="white")
    print(target)


if __name__ == "__main__":
    main()
