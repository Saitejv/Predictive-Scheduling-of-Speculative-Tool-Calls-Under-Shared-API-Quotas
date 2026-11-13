"""Plain-language comparison of the main scheduling strategies from saved results."""

import csv
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
METHODS = [
    ("no_speculation", "Prefetch off: fixed actor path", "#667085"),
    ("current_capacity", "Speculation: capacity only", "#E08036"),
    ("classic_reserve", "Tuned reserve", "#7451A8"),
    ("legacy_jev_full", "Jev: conservative gate", "#79A7CE"),
    ("persistent_jev_full", "Jev: async + late candidates", "#28679C"),
    ("hybrid_jev_full", "Jev + tuned reserve", "#18857D"),
]
SCENARIOS = [
    (
        "hotpot-async-native-50",
        5,
        "Frozen replay: recorded service times",
        "Quota: 12 Search calls every 5 seconds",
    ),
    (
        "hotpot-async-native-50",
        30,
        "Frozen replay: recorded service times",
        "Quota: 12 Search calls every 30 seconds",
    ),
    (
        "hotpot-async-slow-search-50",
        5,
        "Frozen replay: simulated 5-second Searches",
        "Quota: 12 Search calls every 5 seconds",
    ),
    (
        "hotpot-async-slow-search-50",
        30,
        "Frozen replay: simulated 5-second Searches",
        "Quota: 12 Search calls every 30 seconds",
    ),
]


def main():
    selected = []
    sources = {}
    for study, window, heading, quota in SCENARIOS:
        path = ROOT / "results" / study / "summary.json"
        sources[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        rows = json.loads(path.read_text())
        for variant, label, color in METHODS:
            matches = [
                r
                for r in rows
                if (r["agents"], r["capacity"], r["window_s"], r["variant"])
                == (4, 12, window, variant)
            ]
            assert len(matches) == 1, (study, window, variant)
            row = matches[0]
            selected.append(
                {
                    "study": study,
                    "scenario": heading,
                    "quota_calls": 12,
                    "reset_s": window,
                    "workers": 4,
                    "order_seeds": row["seeds"],
                    "variant": variant,
                    "method": label,
                    "mean_completion_s": row["mean_completion_s"],
                    "throughput_questions_s": row["throughput_questions_s"],
                }
            )
    output = ROOT / "docs" / "figures"
    output.mkdir(parents=True, exist_ok=True)
    with (output / "strategy-comparison.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(selected[0]))
        writer.writeheader()
        writer.writerows(selected)
    (output / "strategy-comparison-sources.json").write_text(
        json.dumps(
            {
                "sources": sources,
                "selection": "4 workers; capacity 12; reset 5 or 30 seconds; six implemented strategy packages",
                "cohort": "Same 30 exploratory evaluation questions; five native order seeds, three simulated order seeds",
                "warning": "Prefetch-off is a counterfactual on speculative actor paths, not the live sequential run. Local collection pacing is excluded. Quota labels specify parameters without assuming they are nonbinding. Packages differ in candidate lifetime and admission rule.",
            },
            indent=2,
        )
        + "\n"
    )

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
            "axes.edgecolor": "#C5CBD3",
            "text.color": "#1D2939",
            "axes.labelcolor": "#344054",
            "xtick.color": "#475467",
            "ytick.color": "#1D2939",
        }
    )
    for metric, suffix, xlabel, direction in [
        (
            "mean_completion_s",
            "time",
            "Mean completion time per question (seconds)",
            "Lower is better",
        ),
        (
            "throughput_questions_s",
            "throughput",
            "Completed questions per second, including final background drain",
            "Higher is better",
        ),
    ]:
        fig, axes = plt.subplots(2, 2, figsize=(16, 10.6))
        fig.subplots_adjust(
            left=0.185, right=0.955, top=0.86, bottom=0.16, wspace=0.60, hspace=0.43
        )
        maximum = max(row[metric] for row in selected)
        for ax, (study, window, heading, quota) in zip(axes.flat, SCENARIOS):
            values = [
                next(
                    row[metric]
                    for row in selected
                    if row["study"] == study
                    and row["reset_s"] == window
                    and row["variant"] == method
                )
                for method, _, _ in METHODS
            ]
            bars = ax.barh(
                range(len(METHODS)), values, height=0.65, color=[color for _, _, color in METHODS]
            )
            ax.set_yticks(range(len(METHODS)), [label for _, label, _ in METHODS])
            ax.invert_yaxis()
            ax.set_xlim(0, maximum * 1.16)
            ax.tick_params(axis="y", length=0, pad=9)
            ax.tick_params(axis="x", length=0)
            ax.set_axisbelow(True)
            ax.xaxis.grid(True, color="#E6E9EE", linewidth=0.8)
            ax.set_title(
                f"{heading}\n{quota}", loc="left", fontsize=13, fontweight="normal", pad=15
            )
            for bar, value in zip(bars, values):
                ax.text(
                    value + maximum * 0.015,
                    bar.get_y() + bar.get_height() / 2,
                    f"{value:.2f}" if metric == "mean_completion_s" else f"{value:.4f}",
                    va="center",
                    fontsize=11,
                )
        fig.suptitle(
            "Scheduling replay on one fixed set of actor paths",
            fontsize=23,
            fontweight="normal",
            x=0.055,
            ha="left",
            y=0.98,
        )
        fig.text(
            0.055,
            0.925,
            f"Four agents share one quota  |  {direction}  |  Different comparison from the original live benchmark",
            fontsize=13,
            color="#475467",
        )
        fig.supxlabel(xlabel, fontsize=12, y=0.105)
        fig.text(
            0.055,
            0.068,
            "Same 30 evaluation paths. Five workload orders for recorded service times; three for simulated tool times.",
            fontsize=10.5,
            color="#475467",
        )
        fig.text(
            0.055,
            0.043,
            "Jev uses cross-agent gating. ‘Async + late’ keeps candidates for one further action; ‘Jev + reserve’ adds a quota floor.",
            fontsize=10.5,
            color="#475467",
        )
        fig.text(
            0.055,
            0.021,
            "Actor paths are held fixed; local collection pacing is excluded. Prefetch-off bars are counterfactual, not measured sequential runs.",
            fontsize=10.5,
            color="#475467",
        )
        target = output / f"strategy-comparison-{suffix}.png"
        fig.savefig(target, dpi=170, facecolor="white")
        plt.close(fig)
        print(target)


if __name__ == "__main__":
    main()
