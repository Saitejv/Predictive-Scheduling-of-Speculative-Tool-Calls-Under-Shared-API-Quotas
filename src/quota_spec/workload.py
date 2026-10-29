"""Synthetic fixtures, not HotpotQA traces or a research candidate generator."""

import random

from .models import Call, Step, Task


def synthetic_tasks(agents: int = 4, seed: int = 7) -> tuple[Task, ...]:
    if agents < 1:
        raise ValueError("agents must be positive")
    rng = random.Random(seed)
    tasks = []
    for agent in range(agents):
        steps = []
        for index in range(3):
            query = f"topic-{agent}-hop-{index}"
            candidate = query if rng.random() < 0.75 else f"unused-{agent}-{index}"
            duration = round(rng.uniform(0.5, 2), 3)
            steps.append(
                Step(
                    round(rng.uniform(0.5, 4), 3),
                    Call.search(query),
                    duration,
                    Call.search(candidate),
                    duration,
                )
            )
        arrival = round(rng.uniform(0, 0.5), 3)
        tasks.append(Task(f"agent-{agent}", arrival, tuple(steps), arrival + 30))
    return tuple(tasks)


def dump_tasks(tasks: tuple[Task, ...]) -> list[dict]:
    import json

    return [
        {
            "task_id": t.task_id,
            "arrival_s": t.arrival_s,
            "deadline_s": t.deadline_s,
            "task_context": t.task_context,
            "final_think_s": t.final_think_s,
            "final_candidate_query": json.loads(t.final_candidate.arguments_json)["query"]
            if t.final_candidate
            else None,
            "final_candidate_duration_s": t.final_candidate_duration_s,
            "final_candidate_delay_s": t.final_candidate_delay_s,
            "steps": [
                {
                    "think_s": s.think_s,
                    "query": json.loads(s.required.arguments_json)["query"],
                    "duration_s": s.duration_s,
                    "candidate_query": json.loads(s.candidate.arguments_json)["query"]
                    if s.candidate
                    else None,
                    "candidate_duration_s": s.candidate_duration_s,
                    "result_excerpt": s.result_excerpt,
                    "candidate_delay_s": s.candidate_delay_s,
                }
                for s in t.steps
            ],
        }
        for t in tasks
    ]
