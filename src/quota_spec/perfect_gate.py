"""Exact offline gate enumeration on fixed message/tool dependencies.

A perfect gate never dispatches a candidate absent from the future required
Searches of its own tape. It cannot invent candidates or launch them early.
The exact optimum is conditional on those constraints and FIFO required dispatch.
"""

import time

from .frozen_replay import FrozenReplay


def useful_keys(tapes, *, tool_duration_s=None, max_candidate_age=0, suppress_known_calls=False):
    """Provably complete candidate universe for the original (one-window) lifetime.

    An uncached Search starts both its real tool and its prediction window. The
    latter expires when the next actor returns, after real tool + next actor.
    Quota waiting shifts both equally, so it cannot rescue a later generator.
    """
    keys = []
    for tape in tapes:
        steps = tape["steps"]
        for index, row in enumerate(steps[:-1]):
            window = row["window"]
            if not window:
                continue
            real_tool = row["tool_duration_s"] if tool_duration_s is None else tool_duration_s
            ready_delay = window["observation_duration_s"] + window["hypothetical_duration_s"]
            expiry_delay = real_tool + steps[index + 1]["actor_duration_s"]
            if max_candidate_age == 0 and ready_delay >= expiry_delay:
                continue
            future = {s["query"] for s in steps[index + 1 :] if s["tool"] == "search"}
            for candidate in window["candidates"]:
                if candidate["eligible"] and candidate["query"] in future:
                    if suppress_known_calls:
                        past = {s["query"] for s in steps[: index + 1] if s["tool"] == "search"}
                        if candidate["query"] in past:
                            continue
                        first = next(
                            j
                            for j in range(index + 1, len(steps))
                            if steps[j]["tool"] == "search"
                            and steps[j]["query"] == candidate["query"]
                        )
                        between = steps[index + 1 : first]
                        if not any(s["tool"] == "search" for s in between):
                            first_ready = (
                                real_tool
                                + sum(s["actor_duration_s"] + s["tool_duration_s"] for s in between)
                                + steps[first]["actor_duration_s"]
                            )
                            if ready_delay >= first_ready:
                                continue
                    keys.append((tape["task_id"], index + 1, candidate["rank"]))
    return tuple(sorted(keys))


def subset_keys(keys, mask):
    return frozenset(key for index, key in enumerate(keys) if mask & (1 << index))


def objective(metrics, name):
    if name == "throughput":
        return (metrics["resource_makespan_s"], metrics["mean_completion_s"])
    if name == "latency":
        return (metrics["mean_completion_s"], metrics["resource_makespan_s"])
    raise ValueError("Unknown oracle objective")


def exact_gates(
    tapes,
    capacity,
    window_s,
    *,
    agents,
    keys=None,
    max_bits=12,
    max_candidate_age=0,
    suppress_known_calls=False,
    release_on_answer=False,
    tool_duration_s=None,
    generate_on_reuse=False,
    cache_required_results=False,
):
    """Enumerate EVERY useful subset, separately optimizing mean and throughput.

    post: generate every normally opened window, gate only tool launches.
    pipeline: clairvoyantly skip windows with no selected candidates; retain
    full recorded model times in every selected window. Empty subset = no spec.
    """
    keys = (
        useful_keys(
            tapes,
            max_candidate_age=max_candidate_age,
            suppress_known_calls=suppress_known_calls,
            tool_duration_s=tool_duration_s,
        )
        if keys is None
        else tuple(keys)
    )
    if len(keys) > max_bits:
        raise ValueError(f"Exact gate needs {len(keys)} bits; limit is {max_bits}")
    replay = FrozenReplay(
        tapes,
        capacity,
        window_s,
        max_active_agents=agents,
        max_candidate_age=max_candidate_age,
        suppress_known_calls=suppress_known_calls,
        release_on_answer=release_on_answer,
        tool_duration_s=tool_duration_s,
        generate_on_reuse=generate_on_reuse,
        cache_required_results=cache_required_results,
    )
    winners, scores = {}, []
    started = time.perf_counter()
    evaluations = 0
    for mask in range(1 << len(keys)):
        mask_scores = [mask]
        forced = subset_keys(keys, mask)
        windows = frozenset((tid, step) for tid, step, _ in forced)
        for stage, allowed in [("post", None), ("pipeline", windows)]:
            run = replay.run(
                forced=forced,
                generation_windows=allowed,
                record_events=False,
                record_decisions=False,
            )
            metrics = run["metrics"]
            evaluations += 1
            mask_scores.extend([metrics["mean_completion_s"], metrics["resource_makespan_s"]])
            for target in ["latency", "throughput"]:
                name = stage + "_" + target
                score = (*objective(metrics, target), metrics["speculative_calls"], mask)
                if name not in winners or score < winners[name]["score"]:
                    winners[name] = {
                        "score": score,
                        "mask": mask,
                        "selected": sorted(forced),
                        "metrics": metrics,
                    }
        scores.append(mask_scores)
    for name, row in winners.items():
        stage = name.split("_")[0]
        forced = frozenset(tuple(k) for k in row["selected"])
        allowed = None if stage == "post" else frozenset((tid, step) for tid, step, _ in forced)
        row["run"] = replay.run(forced=forced, generation_windows=allowed)
        if objective(row["run"]["metrics"], name.split("_")[1]) != objective(
            row["metrics"], name.split("_")[1]
        ):
            raise AssertionError("Oracle winner did not reproduce")
    return {
        "exact": True,
        "candidate_bits": len(keys),
        "subsets": 1 << len(keys),
        "schedule_evaluations": evaluations,
        "solver_wall_s": time.perf_counter() - started,
        "keys": keys,
        "winners": winners,
        "scores": scores,
    }
