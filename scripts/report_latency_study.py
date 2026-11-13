"""Render independent audit charts and numerical tables from saved offline runs."""

import argparse
import itertools
import json
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from quota_spec.artifacts import write_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LABELS = {
    "A_none": "A No speculation",
    "B_ungated": "B Recorded, ungated",
    "C_reserve": "C Development reserve",
    "D_jev_own": "D Jev own-agent",
    "D_jev_all": "D Jev all-agent",
    "E_post": "E Search gate: exact native / best-found synthetic",
    "E_pipeline": "E Pipeline gate: exact native / best-found synthetic",
    "F_perfect_predictor": "F Perfect + empty-window screen",
    "F_full_generation": "F Perfect next Search; full generation",
    "G_zero_overhead": "G Next Search, zero generation",
    "H_full_lookahead": "Extra: all future Searches, paid generation",
    "H_full_lookahead_zero": "Extra: all future Searches, zero generation",
}
COLORS = {
    "A_none": "#454545",
    "B_ungated": "#d1495b",
    "C_reserve": "#bc8610",
    "D_jev_own": "#54a4b1",
    "D_jev_all": "#267ab3",
    "E_post": "#a17eb0",
    "E_pipeline": "#8555a1",
    "F_perfect_predictor": "#138572",
    "F_full_generation": "#138572",
    "G_zero_overhead": "#444b9b",
    "H_full_lookahead": "#596f2f",
    "H_full_lookahead_zero": "#9d3d81",
}
DURS = ["native", "scale2", "scale5", "scale10", "fixed1", "fixed2", "fixed5", "fixed10"]


def read(p):
    return json.loads(p.read_text())


def make_report(root):
    completion = read(root / "latency-sweep/completion.json")
    assert completion["complete"]
    rows = read(root / "full-generation-predictor/combined-summary.json")
    arithmetic = read(root / "latency-sweep/noquota-exact-arithmetic.json")
    audit = read(root / "arithmetic-audit.json")
    streams = read(root / "repeated-stream.json")["rows"] + read(
        root / "full-generation-predictor/repeated-stream.json"
    )
    out = root / "figures"
    out.mkdir(exist_ok=True)
    index = {
        (
            r["duration"],
            r["capacity"],
            r["window_s"],
            r["workers"],
            r["release"],
            r["age"],
            r["policy"],
        ): r
        for r in rows
    }

    def get(d, p, c=10000, w=1, n=1, release=True, age=0):
        return index[d, c, w, n, release, age, p]

    def exact(d, field, age=0):
        vals = [
            r[field]
            for r in arithmetic
            if r["duration"] == d and r["age"] == age and r["evaluation"]
        ]
        return statistics.mean(vals)

    def plot_finish(fig, path, footnote, ncol=3):
        handles, labels = fig.axes[0].get_legend_handles_labels()
        fig.legend(
            handles,
            labels,
            loc="lower center",
            ncol=ncol,
            frameon=False,
            fontsize=8,
            bbox_to_anchor=(0.5, 0.005),
        )
        fig.text(0.5, 0.115, footnote, ha="center", fontsize=8)
        fig.tight_layout(rect=(0, 0.15, 1, 0.95))
        fig.savefig(path, dpi=160)
        plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    common_tasks = read(root / "cache-controls/noquota.json")
    common_oracles = read(root / "common-cache-oracles/rows.json")
    common_retention = read(root / "common-cache-retention/rows.json")
    cache_batches = [
        json.loads(x) for x in (root / "cache-controls/rows.jsonl").read_text().splitlines()
    ]

    def common_mean(d, p):
        fields = {
            "A_none": "none_s",
            "E_pipeline": "recorded_gate_exact_s",
            "F_full_generation": "perfect_predictor_s",
        }
        if p in fields:
            return statistics.mean(
                r[fields[p]]
                for r in common_tasks
                if r["duration"] == d and r["evaluation"] and r["cache_required_results"]
            )
        return statistics.mean(
            r["metrics"]["mean_completion_s"]
            for r in common_oracles
            if r["duration"] == d
            and r["evaluation"]
            and r["cache_required_results"]
            and r["variant"] == p
        )

    methods = [
        "A_none",
        "E_pipeline",
        "F_full_generation",
        "G_zero_overhead",
        "H_full_lookahead",
        "H_full_lookahead_zero",
    ]
    for col, durations in enumerate([DURS[:4], DURS[4:]]):
        base = [common_mean(d, "A_none") for d in durations]
        for p in methods:
            vals = [common_mean(d, p) for d in durations]
            label = "E Exact recorded gate, original window" if p == "E_pipeline" else LABELS[p]
            axes[0, col].plot(
                range(4), vals, "o--" if p.startswith("H_") else "o-", label=label, color=COLORS[p]
            )
            axes[1, col].plot(
                range(4),
                [100 * (1 - v / b) for v, b in zip(vals, base)],
                "o-",
                label=label,
                color=COLORS[p],
            )
        for ax in axes[:, col]:
            ax.set_xticks(
                range(4), ["Native", "2×", "5×", "10×"] if col == 0 else ["1", "2", "5", "10"]
            )
            ax.grid(alpha=0.2)
            ax.set_xlabel(
                "Recorded Search duration multiplier"
                if col == 0
                else "Fixed Search service duration (s)"
            )
        axes[0, col].set_ylabel("Mean answer latency (seconds)")
        axes[1, col].set_ylabel("Answer latency reduction vs A (%)")
        axes[1, col].axhline(0, color="#777", lw=0.7)
        axes[0, col].set_title(
            "Recorded native + synthetic scales" if col == 0 else "Synthetic fixed Search durations"
        )
    fig.suptitle("Longer tools make correct speculation more valuable — common cache", fontsize=15)
    plot_finish(
        fig,
        out / "noquota-latency.png",
        "Eval30 · nonbinding 10,000/1 s · required AND speculative results cached · answer latency from task acceptance\n"
        "E: original lifetime. F/G: one next Search, reuse triggers, whole-episode retention. Extra: all future Searches per generation (optimistic).",
    )

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    ps = ["A_none", "E_post", "E_pipeline", "F_full_generation", "D_jev_all"]
    for col, (c, w, n) in enumerate([(12, 30, 4), (6, 60, 2)]):
        for cache, offset, color in [(False, -0.18, "#ca8a32"), (True, 0.18, "#2878b5")]:
            grouped = {
                p: [
                    r["metrics"]
                    for r in cache_batches
                    if (
                        r["capacity"],
                        r["window_s"],
                        r["workers"],
                        r["release"],
                        r["cache_required_results"],
                        r["policy"],
                    )
                    == (c, w, n, False, cache, p)
                ]
                for p in ps
            }
            b = statistics.mean(30 / m["resource_makespan_s"] for m in grouped["A_none"])
            times = [statistics.mean(m["resource_makespan_s"] for m in grouped[p]) for p in ps]
            gains = [
                100 * (statistics.mean(30 / m["resource_makespan_s"] for m in grouped[p]) / b - 1)
                for p in ps
            ]
            label = (
                "Legacy speculative-only cache"
                if not cache
                else "Common required + speculative cache"
            )
            axes[0, col].bar(
                [i + offset for i in range(len(ps))], times, width=0.35, color=color, label=label
            )
            axes[1, col].bar(
                [i + offset for i in range(len(ps))], gains, width=0.35, color=color, label=label
            )
        for ax in axes[:, col]:
            ax.set_xticks(
                range(len(ps)),
                [
                    "No spec",
                    "Exact\nSearch gate",
                    "Exact\npipeline gate",
                    "Perfect\nnext Search",
                    "Jev all",
                ],
            )
            ax.grid(axis="y", alpha=0.2)
        axes[0, col].set_title(f"{n} workers · {c} Searches/{w} s")
        axes[0, col].set_ylabel("All-work batch finish (seconds)")
        axes[1, col].set_ylabel("Throughput gain vs SAME-cache baseline (%)")
        axes[1, col].axhline(0, color="#777", lw=0.7)
    fig.suptitle("The 6.32% example depends on unequal caching rules", fontsize=15)
    plot_finish(
        fig,
        out / "cache-control.png",
        "Native · eval30 · 3 paired orders · drain release · E/Jev: original candidate lifetime\n"
        "Each gain uses its own cache-matched baseline; exact gates. F: full generation, whole-episode retention, reuse triggers.",
        ncol=2,
    )
    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    for col, (c, w, label) in enumerate(
        [
            (10000, 1, "Nonbinding 10,000/1 s"),
            (12, 30, "12 Searches / 30 s"),
            (6, 60, "6 Searches / 60 s"),
        ]
    ):
        for p in [
            "A_none",
            "B_ungated",
            "C_reserve",
            "D_jev_all",
            "E_pipeline",
            "F_full_generation",
            "G_zero_overhead",
        ]:
            vals = [get(d, p, c, w, 4) for d in DURS[:4]]
            axes[0, col].plot(
                range(4),
                [r["resource_makespan_s"] for r in vals],
                "o-",
                label=LABELS[p],
                color=COLORS[p],
            )
            axes[1, col].plot(
                range(4),
                [r["resource_questions_s_gain_pct"] for r in vals],
                "o-",
                label=LABELS[p],
                color=COLORS[p],
            )
        axes[0, col].set_title(label)
        for ax in axes[:, col]:
            ax.set_xticks(range(4), ["Native", "2×", "5×", "10×"])
            ax.set_xlabel("Search duration multiplier")
            ax.grid(alpha=0.2)
        axes[0, col].set_ylabel("All-work finish time (seconds)")
        axes[1, col].set_ylabel("All-work throughput gain vs A (%)")
        axes[1, col].axhline(0, color="#777", lw=0.7)
    fig.suptitle("Shared quota changes the value of longer tools — 4 workers", fontsize=15)
    plot_finish(
        fig,
        out / "shared-quota-latency.png",
        "Legacy speculative-only cache · eval30 · 3 orders · answer release · age 0 · one persistent quota\n"
        "2×/5×/10× synthetic; Jev native-frozen · E synthetic: best-found · F/G: whole-episode retention + reuse triggers; G eager, not quota optimal.",
    )
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    for col, (c, w, label) in enumerate(
        [(10000, 1, "Nonbinding 10,000/1 s"), (12, 30, "12 Searches / 30 s")]
    ):
        for p, release, style, label2 in [
            ("A_none", True, "-", "A No speculation"),
            ("B_ungated", False, "--", "B Recorded, release after drain"),
            ("B_ungated", True, "-", "B Recorded, release at answer"),
            ("D_jev_all", False, "--", "D Jev all, release after drain"),
            ("D_jev_all", True, "-", "D Jev all, release at answer"),
            ("F_full_generation", True, "-", "F Perfect predictor, answer release"),
        ]:
            vals = [get("native", p, c, w, n, release) for n in [1, 2, 4, 8]]
            axes[0, col].plot(
                [1, 2, 4, 8],
                [r["answer_makespan_s"] for r in vals],
                style,
                marker="o",
                label=label2,
                color=COLORS[p],
            )
            axes[1, col].plot(
                [1, 2, 4, 8],
                [r["resource_questions_s_gain_pct"] for r in vals],
                style,
                marker="o",
                label=label2,
                color=COLORS[p],
            )
        axes[0, col].set_title(label)
        for ax in axes[:, col]:
            ax.set_xticks([1, 2, 4, 8])
            ax.set_xlabel("Concurrent main-agent workers")
            ax.grid(alpha=0.2)
        axes[0, col].set_ylabel("All answers ready (seconds)")
        axes[1, col].set_ylabel("All-work throughput gain vs A (%)")
        axes[1, col].axhline(0, color="#777", lw=0.7)
    fig.suptitle("Releasing workers at answer removes repeated drain barriers", fontsize=15)
    plot_finish(
        fig,
        out / "worker-release.png",
        "Legacy speculative-only cache · native · eval30 · 3 orders · B/Jev: original lifetime; F: whole-episode retention + reuse triggers\n"
        "Background work continues and retains quota consumption; bottom panel still waits for all started work to finish.",
    )
    sg = {}
    for r in streams:
        key = (
            r["duration"],
            r["capacity"],
            r["window_s"],
            r["workers"],
            r["release"],
            r["repeats"],
            r["policy"],
        )
        sg.setdefault(key, []).append(r)

    def stream_mean(d, c, w, n, rep, p, field):
        return statistics.mean(r[field] for r in sg[d, c, w, n, True, rep, p])

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    for col, d in enumerate(["native", "scale10"]):
        for row, (c, w) in enumerate([(10000, 1), (12, 30)]):
            ax = axes[row, col]
            for p in ["B_ungated", "D_jev_all", "F_perfect_predictor"]:
                for rep, style in [(1, "--"), (10, "-")]:
                    vals = [
                        100
                        * (
                            stream_mean(d, c, w, n, rep, p, "questions_s")
                            / stream_mean(d, c, w, n, rep, "A_none", "questions_s")
                            - 1
                        )
                        for n in [1, 2, 4, 8]
                    ]
                    ax.plot(
                        [1, 2, 4, 8],
                        vals,
                        style,
                        marker="o",
                        label=f"{LABELS[p]} · {30 * rep} tasks",
                        color=COLORS[p],
                    )
            ax.set_title(
                f"{'Native' if d == 'native' else 'Synthetic 10× Search'} · {'nonbinding' if c == 10000 else '12/30 s'}"
            )
            ax.set_xticks([1, 2, 4, 8])
            ax.set_xlabel("Concurrent main-agent workers")
            ax.set_ylabel("All-work throughput gain vs A (%)")
            ax.grid(alpha=0.2)
            ax.axhline(0, color="#777", lw=0.7)
    fig.suptitle("Finite-batch tails versus repeated workload throughput", fontsize=15)
    plot_finish(
        fig,
        out / "finite-tail.png",
        "Legacy cache · nonbinding = 10,000/1 s · one quota across 30/300 tasks · answer release · B/Jev age 0; F whole-episode + reuse\n"
        "Repeated traces and native-frozen Jev probabilities are diagnostics, not new evidence or a proof of asymptotic steady state.",
    )
    lines = [
        "# Independent latency sweep: numerical tables",
        "",
        "Evaluation30, means of three paired orders. Every modified tool duration is synthetic.",
        "The original sweep retains speculative-only caching. Common-cache controls are a separate, explicit comparison below.",
        "Each row specifies its own quota, workers, lifetime and worker release rule; comparisons never cross those settings.",
        "Latency reduction = 100 × (1 − mean speculative latency / mean baseline latency).",
        "Throughput gain = 100 × (mean per-order tasks/finish time / corresponding baseline − 1).",
        "The two percentages differ. All-work finish includes background drain.",
        "",
        "## Exact no-quota per-question opportunity",
        "",
        "| Search duration | A latency s | Recorded gate, age 0: s / reduction | Recorded gate, age 1: s / reduction | F perfect predictor: s / reduction | G zero generation: s / reduction |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for d in DURS:
        b = exact(d, "none_s")
        vals = [
            exact(d, "recorded_gate_exact_mean_s"),
            exact(d, "recorded_gate_exact_mean_s", 1),
            exact(d, "perfect_predictor_s"),
            exact(d, "zero_overhead_s"),
        ]
        lines.append(
            f"| {d} | {b:.6f} | "
            + " | ".join(f"{v:.6f} / {100 * (1 - v / b):+.3f}%" for v in vals)
            + " |"
        )
    lines += [
        "",
        "E columns above exhaust every useful subset separately per task; these are exact mean-latency optima in the no-quota architecture. They do not assert an exact quota-constrained batch optimum.",
        "F predicts the next required Search, pays each saved source generation duration, generates on cache reuse, never recursively predicts from speculative dispatch, and uses matching required tool service times.",
        "G removes only generation duration in that same one-step architecture. Its no-quota mean is an upper reference for that architecture. The eager G policy under binding quotas is not a globally optimized upper bound.",
        "",
        "## Four-worker answer-release comparisons",
        "",
        "Original candidate lifetime, no extra duplicate suppression for B/C/D/E; one persistent quota. E is exact at native timings (nine bits), otherwise a feasible best-found pipeline gate.",
        "",
        "| Quota | Search duration | Policy | Mean answer s | All answers s | All work s | All-work throughput gain | E exact? |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for c, w in [(10000, 1), (12, 30), (6, 60)]:
        for d in DURS:
            for p in [
                "A_none",
                "B_ungated",
                "C_reserve",
                "D_jev_own",
                "D_jev_all",
                "E_post",
                "E_pipeline",
                "F_full_generation",
                "G_zero_overhead",
            ]:
                r = get(d, p, c, w, 4)
                lines.append(
                    f"| {c}/{w}s | {d} | {p} | {r['mean_completion_s']:.3f} | {r['answer_makespan_s']:.3f} | {r['resource_makespan_s']:.3f} | {r['resource_questions_s_gain_pct']:+.3f}% | {r.get('exact', '')} |"
                )
    lines += [
        "",
        "## Worker release and retention: native and synthetic 10×",
        "",
        "| Duration | Quota | Workers | Release | Retention | Policy | Mean answer s | All answers s | All work s | Throughput gain |",
        "|---|---|---:|---|---|---|---:|---:|---:|---:|",
    ]
    for d, cw, n, release, age in itertools.product(
        ["native", "scale10"], [(10000, 1), (12, 30), (6, 60)], [1, 2, 4, 8], [False, True], [0, 1]
    ):
        for p in ["A_none", "B_ungated", "D_jev_all", "E_pipeline", "F_perfect_predictor"]:
            r = get(d, p, *cw, n, release, age)
            lines.append(
                f"| {d} | {cw[0]}/{cw[1]}s | {n} | {'answer' if release else 'drain'} | {'one extra action + dedup' if age else 'original'} | {p} | {r['mean_completion_s']:.3f} | {r['answer_makespan_s']:.3f} | {r['resource_makespan_s']:.3f} | {r['resource_questions_s_gain_pct']:+.3f}% |"
            )
    lines += [
        "",
        "## Repeated-stream diagnostic",
        "",
        "Answer release, original lifetime. Mean questions/s over three orders, converted to improvement against the same repeated no-speculation stream. Interior gain uses the 10%–90% interval of ordered answer finishes; it reduces endpoints without proving stationarity.",
        "",
        "| Duration | Quota | Workers | Tasks | Policy | All-work s | Throughput gain | Interior throughput gain |",
        "|---|---|---:|---:|---|---:|---:|---:|",
    ]
    for d, cw, n, rep, p in itertools.product(
        ["native", "scale10"],
        [(10000, 1), (12, 30), (6, 60)],
        [1, 2, 4, 8],
        [1, 10],
        ["B_ungated", "D_jev_all", "F_full_generation", "G_zero_overhead"],
    ):
        c, w = cw
        t = stream_mean(d, c, w, n, rep, p, "resource_makespan_s")
        gain = 100 * (
            stream_mean(d, c, w, n, rep, p, "questions_s")
            / stream_mean(d, c, w, n, rep, "A_none", "questions_s")
            - 1
        )
        interior = 100 * (
            stream_mean(d, c, w, n, rep, p, "interior_questions_s")
            / stream_mean(d, c, w, n, rep, "A_none", "interior_questions_s")
            - 1
        )
        lines.append(
            f"| {d} | {c}/{w}s | {n} | {30 * rep} | {p} | {t:.3f} | {gain:+.3f}% | {interior:+.3f}% |"
        )

    lookahead = read(root / "oracle-lookahead/rows.json")
    controls = read(root / "retention-controls/rows.json")
    architecture = read(root / "oracle-architecture/rows.json")
    lines += [
        "",
        "## Extra full-lookahead oracle (different architecture)",
        "",
        "The requested F/G predict one next Search. Here one saved generation reveals ALL distinct later Searches; this is a stronger and optimistic capability. Tool times are still charged. It is not evidence that a real model can emit the full future chain at the same cost.",
        "",
        "| Duration | A mean s | Full lookahead, measured generation s / reduction | Full lookahead, zero generation s / reduction |",
        "|---|---:|---:|---:|",
    ]
    for d in DURS:
        b = exact(d, "none_s")
        vals = [
            statistics.mean(
                r["metrics"]["mean_completion_s"]
                for r in lookahead
                if r["duration"] == d and r["evaluation"] and r["zero_overhead"] == z
            )
            for z in [False, True]
        ]
        lines.append(
            f"| {d} | {b:.6f} | "
            + " | ".join(f"{v:.6f} / {100 * (1 - v / b):+.3f}%" for v in vals)
            + " |"
        )
    lines += [
        "",
        "## Retention and duplicate suppression separated",
        "",
        "Exact no-quota recorded-gate mean latency, evaluation30. Suppression excludes all historically requested Searches, including ordinary results which are NOT cached for reuse. It can therefore remove useful speculative caching of repeated queries. The main quota sweep explicitly compares the bundled age0/no-suppression and age1/suppression variants.",
        "",
        "| Duration | Original, no suppression s | Original + suppression s | Extra action, no suppression s | Extra action + suppression s |",
        "|---|---:|---:|---:|---:|",
    ]
    for d in DURS:
        vals = [
            statistics.mean(
                r["exact_gate_latency_s"]
                for r in controls
                if r["duration"] == d and r["evaluation"] and r["age"] == a and r["suppress"] == sup
            )
            for a, sup in [(0, False), (0, True), (1, False), (1, True)]
        ]
        lines.append(f"| {d} | " + " | ".join(f"{v:.6f}" for v in vals) + " |")
    lines += [
        "",
        "## Perfect-predictor trigger and empty-window controls",
        "",
        "Evaluation30, one task at a time, nonbinding quota. Isolated task resource times below include its started generation. Do not sum them to estimate a stream with answer release, because background work overlaps later tasks.",
        "",
        "| Duration | Variant | Mean answer s | Mean isolated-task resource s |",
        "|---|---|---:|---:|",
    ]
    for d in DURS:
        for v in sorted({r["variant"] for r in architecture if r["variant"].startswith("F_")}):
            vals = [
                r["metrics"]
                for r in architecture
                if r["duration"] == d and r["evaluation"] and r["variant"] == v
            ]
            lines.append(
                f"| {d} | {v} | {statistics.mean(r['mean_completion_s'] for r in vals):.6f} | {statistics.mean(r['resource_makespan_s'] for r in vals):.6f} |"
            )
    gates = [json.loads(x) for x in (root / "predictor-gates/rows.jsonl").read_text().splitlines()]
    lines += [
        "",
        "## Perfect candidate accuracy plus global admission",
        "",
        "Answer release, next-Search oracle, native or synthetic 10×, three orders. These additional globally gated schedules are feasible best-found subsets, NOT exact optima. Both eager and gated columns below share the empty-source screen; main F charts charge full terminal generation instead.",
        "",
        "| Duration | Quota | Workers | F screened eager all-work s / throughput gain | F screened + best-found pipeline gate s / gain |",
        "|---|---|---:|---:|---:|",
    ]
    for d, cw, n in itertools.product(["native", "scale10"], [(12, 30), (6, 60)], [1, 2, 4, 8]):
        c, w = cw
        eager = get(d, "F_perfect_predictor", c, w, n)
        vals = [
            r["metrics"]
            for r in gates
            if (r["duration"], r["capacity"], r["window_s"], r["workers"], r["policy"])
            == (d, c, w, n, "F_gate_pipeline")
        ]
        mean = statistics.mean(r["resource_makespan_s"] for r in vals)
        gain = 100 * (
            statistics.mean(30 / r["resource_makespan_s"] for r in vals)
            / get(d, "A_none", c, w, n)["resource_questions_s"]
            - 1
        )
        lines.append(
            f"| {d} | {c}/{w}s | {n} | {eager['resource_makespan_s']:.6f} / {eager['resource_questions_s_gain_pct']:+.3f}% | {mean:.6f} / {gain:+.3f}% |"
        )

    lines += [
        "",
        "## Common-cache no-quota opportunity",
        "",
        "Both ordinary required results and speculative results are cached per task. These reductions compare to the SAME common-cache baseline. E is exact per task, with original lifetime; extended E uses whole-episode retention. F retains measured generation, G sets it to zero; extra H has full future lookahead at one source generation.",
        "",
        "| Duration | A mean s | E original s / reduction | E whole episode s / reduction | F next Search s / reduction | G next Search, zero G s / reduction | H full future, paid G s / reduction | H full future, zero G s / reduction |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for d in DURS:
        b = common_mean(d, "A_none")
        extended = statistics.mean(
            r["exact_gate_latency_s"]
            for r in common_retention
            if r["duration"] == d and r["evaluation"] and r["age"] == 999 and r["suppress"]
        )
        vals = [common_mean(d, "E_pipeline"), extended] + [
            common_mean(d, p)
            for p in [
                "F_full_generation",
                "G_zero_overhead",
                "H_full_lookahead",
                "H_full_lookahead_zero",
            ]
        ]
        lines.append(
            f"| {d} | {b:.6f} | "
            + " | ".join(f"{v:.6f} / {100 * (1 - v / b):+.3f}%" for v in vals)
            + " |"
        )
    lines += [
        "",
        "## Cache semantics: matched native batch controls",
        "",
        "Each row uses its own cache rule as baseline. E gates enumerate every subset. Quota shared for entire eval30 batch. F pays full terminal generation; next-Search plus reuse triggers.",
        "",
        "| Quota | Workers | Cache | Release | Policy | Mean answer s | All answers s | All work s | Throughput gain vs same cache |",
        "|---|---:|---|---|---|---:|---:|---:|---:|",
    ]
    for c, w, n in [(10000, 1, 1), (12, 30, 4), (6, 60, 2)]:
        for cache, release in itertools.product([False, True], [False, True]):
            group = [
                r
                for r in cache_batches
                if (
                    r["capacity"],
                    r["window_s"],
                    r["workers"],
                    r["release"],
                    r["cache_required_results"],
                )
                == (c, w, n, release, cache)
            ]
            b = statistics.mean(
                30 / r["metrics"]["resource_makespan_s"] for r in group if r["policy"] == "A_none"
            )
            for p in [
                "A_none",
                "B_ungated",
                "D_jev_all",
                "E_post",
                "E_pipeline",
                "F_full_generation",
            ]:
                vals = [r["metrics"] for r in group if r["policy"] == p]
                metrics = [
                    statistics.mean(r[k] for r in vals)
                    for k in ["mean_completion_s", "answer_makespan_s", "resource_makespan_s"]
                ]
                gain = 100 * (statistics.mean(30 / r["resource_makespan_s"] for r in vals) / b - 1)
                lines.append(
                    f"| {c}/{w}s | {n} | {'common' if cache else 'speculative only'} | {'answer' if release else 'drain'} | {p} | "
                    + " | ".join(f"{v:.6f}" for v in metrics)
                    + f" | {gain:+.3f}% |"
                )
    path = ROOT / "docs/INDEPENDENT_LATENCY_TABLES_2026-11-13.md"
    path.write_text("\n".join(lines) + "\n")
    write_json(
        root / "chart-sources.json",
        {
            "sweep": str(root / "full-generation-predictor/combined-summary.json"),
            "exact_per_task": str(root / "latency-sweep/noquota-exact-arithmetic.json"),
            "streams": str(root / "repeated-stream.json"),
            "rows": len(rows),
            "policy_runs": completion["rows"]
            + read(root / "full-generation-predictor/completion.json")["rows"],
            "arithmetic_checks": audit["reference_checks"],
        },
    )
    print("Created five charts and numerical tables", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    a = p.parse_args()
    make_report(a.root)
