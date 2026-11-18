"""Compact speed-only report; keep large and small cohorts separate."""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

from quota_spec.artifacts import write_json

PREFIX = Path("results")
STEM = "team-context-2026-11-17-"
FIELDS = [
    "mean_completion_s",
    "resource_makespan_s",
    "p95_completion_s",
    "mean_required_wait_s",
    "speculative_calls",
    "unused_speculative_calls",
    "predictor_overhead_s",
]


def read(suffix):
    return json.loads((PREFIX / (STEM + suffix) / "rows.json").read_text())


def csv_file(path, rows):
    with path.open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def aggregate(rows):
    grouped = defaultdict(list)
    keys = ["agents", "capacity", "window_s", "search_s", "policy"]
    for row in rows:
        grouped[tuple(row[k] for k in keys)].append(row)
    return [
        {
            **dict(zip(keys, group)),
            "paired_orders": len(values),
            **{f: mean(r[f] for r in values) for f in FIELDS},
        }
        for group, values in grouped.items()
    ]


def table(rows, policies, *, service_filter=None, counts=(4, 8), metric="mean_completion_s"):
    groups = defaultdict(dict)
    for row in rows:
        if row["agents"] not in counts or row["capacity"] == 1000000:
            continue
        if service_filter is not None and row["search_s"] not in service_filter:
            continue
        groups[(row["agents"], row["capacity"], row["window_s"], row["search_s"])][
            row["policy"]
        ] = row[metric]
    labels = {
        "none": "No speculation",
        "all": "Full",
        "all_budget4": "Full, step 4",
        "jev_full": "Jev global",
        "jev_own": "Jev owner objective",
        "quota": "Quota LLM",
        "phases": "+ peer progress",
        "team": "+ full peer context",
    }
    lines = [
        "| Workers | Quota | Search response | " + " | ".join(labels[p] for p in policies) + " |",
        "|---:|:---|---:|" + "---:|" * len(policies),
    ]
    for (a, c, w, d), values in sorted(
        groups.items(), key=lambda pair: (pair[0][:3], pair[0][3] or 0)
    ):
        ds = "Captured" if d is None else f"{d:g}s"
        lines.append(
            f"| {a} | {c}/{w:g}s | {ds} | "
            + " | ".join(f"{values[p]:.2f}" for p in policies)
            + " |"
        )
    return "\n".join(lines) + "\n"


def report(output):
    output.mkdir(parents=True, exist_ok=False)
    large = aggregate(read("latency"))
    small = {}
    for source in ("gates-enum", "phases", "matched-jev"):
        for row in read(source):
            key = tuple(
                row[k] for k in ("agents", "capacity", "window_s", "search_s", "seed", "policy")
            )
            value = {
                k: row[k]
                for k in (
                    "agents",
                    "capacity",
                    "window_s",
                    "search_s",
                    "seed",
                    "policy",
                    "tasks",
                    *FIELDS,
                )
            }
            if key in small:
                assert value == small[key], "Repeated baseline differs"
            small[key] = value
    compact = list(small.values())
    csv_file(output / "latency-80-questions.csv", large)
    csv_file(output / "context-8-questions.csv", compact)
    write_json(output / "latency-aggregate.json", large)
    write_json(output / "context-rows.json", compact)
    (output / "latency-table.md").write_text(
        table(large, ["none", "all", "jev_own", "jev_full"], service_filter=(0.1, 1.0, 3.0))
    )
    (output / "context-table.md").write_text(
        table(compact, ["none", "all", "jev_full", "quota", "phases", "team"])
    )
    (output / "batch-table.md").write_text(
        table(
            large,
            ["none", "all", "jev_own", "jev_full"],
            service_filter=(0.1, 1.0, 3.0),
            metric="resource_makespan_s",
        )
    )
    costs = json.loads((PREFIX / (STEM + "costs.json")).read_text())
    write_json(output / "costs.json", costs)
    audits = {
        s: json.loads((PREFIX / (STEM + s) / "independent-audit.json").read_text())
        for s in ["latency", "gates-enum", "phases", "matched-jev"]
    }
    assert all(a["passed"] for a in audits.values())
    write_json(output / "audits.json", audits)
    wins = []
    for row in large:
        if row["policy"] != "jev_full":
            continue
        controls = {
            r["policy"]: r
            for r in large
            if all(r[k] == row[k] for k in ("agents", "capacity", "window_s", "search_s"))
        }
        if all(
            row[f] < controls[p][f] - 1e-6
            for f in ["mean_completion_s", "resource_makespan_s"]
            for p in ["none", "all"]
        ):
            wins.append(
                {
                    **row,
                    "savings_percent": {
                        f: {p: 100 * (1 - row[f] / controls[p][f]) for p in ["none", "all"]}
                        for f in ["mean_completion_s", "resource_makespan_s"]
                    },
                }
            )
    write_json(output / "dual-wins.json", wins)
    # Standalone scientific figure, kept separate from the small paid gate cohort.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(10, 6.5), sharex=True, sharey=True)
    for ax, (a, c, w) in zip(
        axes.flat, [(4, 12, 3), (4, 8, 5), (8, 12, 3), (8, 8, 5)], strict=True
    ):
        for policy, label, color, style in [
            ("all", "Full speculation", "#c64c39", "-"),
            ("jev_own", "Jev: owner objective", "#299585", "--"),
            ("jev_full", "Jev: global objective", "#6244a5", "-"),
        ]:
            ratios = []
            for d in [0.1, 1.0, 3.0]:
                cell = {
                    r["policy"]: r
                    for r in large
                    if (r["agents"], r["capacity"], r["window_s"], r["search_s"]) == (a, c, w, d)
                }
                ratios.append(cell[policy]["mean_completion_s"] / cell["none"]["mean_completion_s"])
            ax.plot(
                [0.1, 1.0, 3.0], ratios, style, marker="o", label=label, color=color, linewidth=2
            )
        ax.axhline(1, color="#333333", linestyle=":", label="No speculation")
        ax.set_title(f"{a} workers · {c} Search calls / {w}s")
        ax.set_xscale("log")
        ax.set_xticks([0.1, 1.0, 3.0], ["0.1", "1", "3"])
        ax.grid(alpha=0.2)
        ax.set_ylabel("Latency / no-spec latency")
    for ax in axes[-1]:
        ax.set_xlabel("Configured Search response time (seconds)")
    axes[0, 0].legend(fontsize=8)
    fig.suptitle(
        "Longer Search response times can change the winning policy\n80 fixed questions · 3 paired orders · lower is better",
        fontsize=12,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(output / "latency-sweep.png", dpi=180)
    print(
        json.dumps(
            dict(
                large_settings=len(large) // 5,
                replay_runs=900,
                small_unique_runs=len(compact),
                dual_win_settings=len(wins),
                api_cost_usd=costs["known_cost_usd"],
            )
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    report(p.parse_args().output)
