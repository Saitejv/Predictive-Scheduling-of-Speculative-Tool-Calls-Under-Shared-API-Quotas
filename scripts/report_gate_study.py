"""Render the deterministic gate sweep without making inference requests."""

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

METHODS = [
    ("none", "No speculation", "#444444"),
    ("ungated", "Speculation, no predictive gate", "#d1495b"),
    ("reserve_pipeline", "Tuned reserve + generation screen", "#e49b0f"),
    ("jev_full", "Jev, all-agent context", "#2878b5"),
    ("ideal_post", "Perfect Search gate", "#8c55a2"),
    ("ideal_pipeline", "Perfect gate + selective generation", "#138572"),
]


def read(path):
    return json.loads(path.read_text())


def lookup(rows):
    return {(r["capacity"], r["window_s"], r["agents"], r["policy"]): r for r in rows}


def method_key(method, target):
    return method + "_" + target if method.startswith("ideal_") else method


def make_panels(rows, settings, path, *, title):
    index = lookup(rows)
    counts = [1, 2, 4, 8]
    fig, axes = plt.subplots(2, len(settings), figsize=(14, 8), squeeze=False)
    for col, (capacity, window, label) in enumerate(settings):
        for method, name, color in METHODS:
            latency = [
                index[capacity, window, n, method_key(method, "latency")]["mean_completion_s"]
                for n in counts
            ]
            throughput = [
                index[capacity, window, n, method_key(method, "throughput")][
                    "throughput_gain_percent"
                ]
                for n in counts
            ]
            axes[0, col].plot(counts, latency, marker="o", color=color, label=name)
            axes[1, col].plot(counts, throughput, marker="o", color=color, label=name)
        axes[0, col].set_title(label)
        axes[1, col].axhline(0, color="#666666", lw=0.8)
        for row in range(2):
            ax = axes[row, col]
            ax.set_xticks(counts)
            ax.set_xlabel("Concurrent agent workers")
            ax.grid(alpha=0.2)
        axes[0, col].set_ylabel("Mean answer time per question (seconds)")
        axes[1, col].set_ylabel("Batch throughput gain vs no speculation (%)")
    fig.suptitle(title, fontsize=15)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False, fontsize=10)
    fig.text(
        0.5,
        0.095,
        "Measured service times · eval30 · mean of 3 orders · one persistent fixed-window quota\n"
        "Top: latency-optimal perfect gates. Bottom: throughput-optimal perfect gates. Separate schedules.",
        ha="center",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0.14, 1, 0.94))
    fig.savefig(path, dpi=180)
    plt.close(fig)


def make_heatmap(rows, path):
    index = lookup(rows)
    settings = [(10000, 1)] + [(c, w) for c in [1, 3, 6, 12] for w in [1, 5, 10, 30, 60]]
    methods = ["ungated", "reserve_pipeline", "jev_full", "ideal_post", "ideal_pipeline"]
    names = dict((m, n) for m, n, _ in METHODS)
    fig, axes = plt.subplots(1, 5, figsize=(15, 10), sharey=True)
    for ax, method in zip(axes, methods):
        data = np.array(
            [
                [
                    index[c, w, n, method_key(method, "throughput")]["throughput_gain_percent"]
                    for n in [1, 2, 4, 8]
                ]
                for c, w in settings
            ]
        )
        im = ax.imshow(data, cmap="RdYlGn", vmin=-16, vmax=16, aspect="auto")
        ax.set_title(names[method].replace(", ", "\n").replace(" + ", "\n+ "), fontsize=10)
        ax.set_xticks(range(4), [1, 2, 4, 8])
        ax.set_xlabel("Agent workers")
        for i in range(len(settings)):
            for j in range(4):
                ax.text(j, i, f"{data[i, j]:+.1f}", ha="center", va="center", fontsize=7)
    axes[0].set_yticks(
        range(len(settings)), ["Nonbinding"] + [f"{c} / {w}s" for c, w in settings[1:]]
    )
    axes[0].set_ylabel("Search calls allowed per fixed reset window")
    fig.suptitle("Global throughput change vs no speculation (%) — original candidate lifetime")
    fig.subplots_adjust(left=0.09, right=0.89, top=0.9, bottom=0.06, wspace=0.15)
    color_axis = fig.add_axes((0.92, 0.23, 0.015, 0.5))
    fig.colorbar(im, cax=color_axis, label="Positive is faster")
    fig.savefig(path, dpi=180)
    plt.close(fig)


def tables(rows, *, extended=False):
    index = lookup(rows)
    settings = sorted({(r["capacity"], r["window_s"]) for r in rows})
    settings.sort(key=lambda s: (s[0] != 10000, s[0], s[1]))
    lines = [
        "# Extended candidate lifetime" if extended else "# Original candidate lifetime",
        "",
        "Evaluation30; three question orders. Times are seconds. Positive throughput change is faster.",
        "Mean answer time starts at worker acceptance; batch makespan includes every task and resource drain.",
        "The ideal columns optimize the metric shown, and can use different schedules in the two tables.",
        "",
    ]
    for field, title, objective in [
        ("mean_completion_s", "Mean answer time", "latency"),
        ("throughput_gain_percent", "Batch throughput change (%)", "throughput"),
        ("resource_makespan_s", "Full batch resource makespan", "throughput"),
    ]:
        lines += [
            "## " + title,
            "",
            "| Quota | Agents | None | Ungated | Reserve | Jev own | Jev all | Perfect Search | Perfect pipeline |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for c, w in settings:
            for n in [1, 2, 4, 8]:
                values = [
                    index[c, w, n, method_key(p, objective)][field]
                    for p in [
                        "none",
                        "ungated",
                        "reserve_pipeline",
                        "jev_own",
                        "jev_full",
                        "ideal_post",
                        "ideal_pipeline",
                    ]
                ]
                label = "Nonbinding" if c == 10000 else f"{c}/{w}s"
                lines.append(f"| {label} | {n} | " + " | ".join(f"{v:.3f}" for v in values) + " |")
        lines.append("")
    return "\n".join(lines)


def main(main_dir, extended_dir, output):
    output.mkdir(parents=True, exist_ok=True)
    rows = read(main_dir / "summary.json")
    ext = read(extended_dir / "summary.json")
    make_panels(
        rows,
        [(10000, 1, "Nonbinding Search quota"), (12, 30, "12 Searches per 30-second reset")],
        output / "full-gate-comparison.png",
        title="Same main-agent messages and tool durations: what does each gate change?",
    )
    make_panels(
        ext,
        [(10000, 1, "Nonbinding Search quota"), (12, 30, "12 Searches per 30-second reset")],
        output / "full-gate-extended-comparison.png",
        title="Let candidates survive one extra main-agent action, with duplicate suppression",
    )
    make_panels(
        rows,
        [(6, 60, "6 Searches per 60-second reset"), (12, 60, "12 Searches per 60-second reset")],
        output / "full-gate-reset-opportunity.png",
        title="A useful prefetch can avoid a reset; wasted speculation can add one",
    )
    make_heatmap(rows, output / "full-gate-throughput-grid.png")
    (output.parent / "FULL_GATE_TABLES_2026-11-13.md").write_text(tables(rows))
    (output.parent / "FULL_GATE_EXTENDED_TABLES_2026-11-13.md").write_text(
        tables(ext, extended=True)
    )
    sources = [main_dir / "summary.json", extended_dir / "summary.json", Path(__file__)]
    (output / "full-gate-sources.json").write_text(
        json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}, indent=2)
        + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("main", type=Path)
    parser.add_argument("extended", type=Path)
    parser.add_argument("--output", type=Path, default=Path("docs/figures"))
    args = parser.parse_args()
    main(args.main, args.extended, args.output)
