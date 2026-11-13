"""Derive the Jev sensitivity report and figures solely from saved replay rows."""

import json
import random
import statistics
from pathlib import Path

from quota_spec.artifacts import write_json
from quota_spec.frozen_replay import load_dataset
from quota_spec.prediction import calibration
from quota_spec.tape_forecasts import TapeHistory, cases

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    root = ROOT / "results" / ("hotpot-forecast-quota-" + name)
    return [json.loads(line) for line in (root / "rows.jsonl").read_text().splitlines()]


def paired(rows, capacity, window, agents, policy, baseline):
    def selected(name):
        return {
            r["seed"]: r
            for r in rows
            if r["capacity"] == capacity
            and r["window_s"] == window
            and r["agents"] == agents
            and r["policy"] == name
        }

    a, b = selected(policy), selected(baseline)
    seeds = sorted(set(a) & set(b))
    delta = [b[s]["mean_completion_s"] - a[s]["mean_completion_s"] for s in seeds]
    rng = random.Random(711)
    sampled = sorted(statistics.mean(rng.choices(delta, k=len(delta))) for _ in range(5000))
    return {
        "capacity": capacity,
        "window_s": window,
        "agents": agents,
        "policy": policy,
        "baseline": baseline,
        "saving_s": statistics.mean(delta),
        "saving_percent": 100
        * statistics.mean(delta)
        / statistics.mean(b[s]["mean_completion_s"] for s in seeds),
        "order_seed_bootstrap95_s": [sampled[125], sampled[4874]],
        "seed_saving_range_s": [min(delta), max(delta)],
        "throughput_gain_percent": 100
        * (
            statistics.mean(a[s]["throughput_questions_s"] for s in seeds)
            / statistics.mean(b[s]["throughput_questions_s"] for s in seeds)
            - 1
        ),
    }


def main():
    native = load("native-full-reserves")
    slow = load("slow-search-full-reserves")
    latency = load("native-latency-final")
    horizon = load("horizon90")
    comparisons = []
    for rows, c, w, a, policy, baseline in [
        (native, 12, 60, 4, "jev_full", "jev_own"),
        (native, 12, 60, 4, "jev_full", "current_capacity"),
        (slow, 6, 30, 4, "jev_full", "jev_own"),
        (slow, 6, 60, 4, "jev_full", "jev_own"),
        (slow, 12, 30, 4, "jev_full", "jev_own"),
        (slow, 12, 60, 8, "jev_full", "jev_own"),
        (slow, 12, 30, 4, "jev_full", "no_speculation"),
        (slow, 6, 5, 4, "jev_full", "no_speculation"),
        (horizon, 12, 30, 4, "jev_full", "jev_own"),
    ]:
        comparisons.append(paired(rows, c, w, a, policy, baseline))
    data = load_dataset(ROOT / "results/hotpot-dataset-50")
    history = TapeHistory(data["tapes"][:20])
    cal = {}
    evalcases = list(cases(data["tapes"][20:]))
    for field in ["reuse", "next", "continues"]:
        attr = {
            "reuse": "reuse_probability",
            "next": "next_probability",
            "continues": "continue_probability",
        }[field]
        cal[field] = calibration(
            [
                (getattr(history.predict(state, agent), attr), labels[field])
                for _, state, agent, labels in evalcases
                if labels[field] is not None and (field == "next" or labels["next"])
            ]
        )
    result = {
        "comparisons": comparisons,
        "history_evaluation_calibration": cal,
        "primary_runs": len(native),
        "sensitivity_runs": len(slow) + len(latency) + len(horizon),
        "validation": "Every reported replay checked frozen answers, quota capacity per window, drained worker limits, no predictor fallback; network sockets blocked",
        "interval_warning": "Bootstrap resamples 3 or 5 workload-order seeds on the same 30 fixed questions; not population confidence or independent model trials",
    }
    out = ROOT / "results/jev-study-analysis"
    out.mkdir(exist_ok=True)
    write_json(out / "analysis.json", result)
    for comparison in comparisons:
        print(comparison)
    print(
        "history calibration",
        {k: {a: b for a, b in v.items() if a != "bins"} for k, v in cal.items()},
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 2, figsize=(13, 8.5), layout="constrained")
    colors = {
        "no_speculation": "#64748b",
        "current_capacity": "#f97316",
        "fixed_reserve": "#8b5cf6",
        "jev_own": "#e11d48",
        "jev_full": "#0891b2",
    }
    labels = {
        "no_speculation": "No spec",
        "current_capacity": "Capacity",
        "fixed_reserve": "Reserve",
        "jev_own": "Jev own",
        "jev_full": "Jev full",
    }

    def mean(rows, c, w, a, p, key="mean_completion_s"):
        return statistics.mean(
            r[key]
            for r in rows
            if r["capacity"] == c and r["window_s"] == w and r["agents"] == a and r["policy"] == p
        )

    for ax, rows, c, w, a, title in [
        (axes[0, 0], native, 12, 60, 4, "Recorded Search timings | 12 calls / 60 s | 4 workers"),
        (axes[0, 1], slow, 12, 30, 4, "Synthetic 5 s Search | 12 calls / 30 s | 4 workers"),
    ]:
        policies = list(colors)
        values = [mean(rows, c, w, a, p) for p in policies]
        bars = ax.bar([labels[p] for p in policies], values, color=[colors[p] for p in policies])
        ax.bar_label(bars, fmt="%.1f", padding=3)
        ax.set_ylabel("Mean question completion (s)")
        ax.set_title(title, fontsize=11)
        ax.set_ylim(0, max(values) * 1.18)
    ax = axes[1, 0]
    for p in ["no_speculation", "fixed_reserve", "jev_own", "jev_full"]:
        ax.plot(
            [5, 30, 60],
            [mean(slow, 6, w, 4, p) for w in [5, 30, 60]],
            marker="o",
            color=colors[p],
            label=labels[p],
        )
    ax.set_title("Synthetic 5 s Search | fixed capacity 6 | 4 workers", fontsize=11)
    ax.set_xlabel("Quota reset period (s)")
    ax.set_ylabel("Mean question completion (s)")
    ax.legend(frameon=False)
    ax = axes[1, 1]
    settings = [(1, 5), (2, 10), (6, 30), (12, 60)]
    for p in ["no_speculation", "current_capacity", "fixed_reserve", "jev_full"]:
        ax.plot(
            range(4),
            [mean(native, c, w, 4, p) for c, w in settings],
            marker="o",
            color=colors[p],
            label=labels[p],
        )
    ax.set_xticks(range(4), [f"{c} / {w}s" for c, w in settings])
    ax.set_title("Recorded timings | same 0.2 calls/s | 4 workers", fontsize=11)
    ax.set_xlabel("Capacity / reset period")
    ax.set_ylabel("Mean question completion (s)")
    ax.legend(frameon=False)
    fig.suptitle(
        "Jev quota experiments: cross-agent protection helps, simple reserves remain strong",
        fontsize=14,
    )
    target = ROOT / "docs/figures/jev-quota-study.png"
    fig.savefig(target, dpi=180)
    print(target)


if __name__ == "__main__":
    main()
