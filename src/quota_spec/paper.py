"""Pinned upstream HotpotQA baseline, with OpenRouter transport and provenance.

This runs the authors' ReAct/Wikipedia observation-speculation experiment.
It deliberately does not route through the separate local-BM25 QA workload.
The upstream runner measures action agreement serially, not live speedup.
"""

import argparse
import copy
import hashlib
import json
import os
import time
from contextvars import ContextVar
from pathlib import Path

from .artifacts import write_json
from .telemetry import summarize_inference

# Compatibility exports: reference collectors keep their historical imports.
from .upstream import (
    FILES as FILES,
)
from .upstream import (
    REPOSITORY as REPOSITORY,
)
from .upstream import (
    REVISION as REVISION,
)
from .upstream import (
    load_upstream as load_upstream,
)
from .upstream import (
    paper_indices as paper_indices,
)
from .upstream import (
    prepare as prepare,
)
from .upstream import (
    working_directory as working_directory,
)

INFERENCE_CONTEXT = ContextVar("paper_inference_context", default={})


def compatibility_fixes(module):
    """Correct task selection and keep speculative observations branch-local."""
    history = module.wrappers.HistoryWrapper

    def reset(self, seed=None, return_info=False, options=None, idx=None):
        output = self.env.reset(seed=seed, return_info=return_info, options=options, idx=idx)
        self.normal_trajectory_dict = self.get_empty_traj_dict()
        self.sim_trajectory_dict = self.get_empty_traj_dict()
        return output

    history.reset = reset
    environment = module.environment.WikiEnv
    original_step = environment.step

    def step(self, action, step_type="wiki"):
        if step_type != "simulate":
            return original_step(self, action, step_type)
        # Upstream guess_step overwrites the real page and lookup cursor. Keep
        # predicted observations available, but restore authoritative tool state.
        fields = ("page", "obs", "lookup_keyword", "lookup_list", "lookup_cnt", "steps", "answer")
        saved = {key: copy.deepcopy(getattr(self, key)) for key in fields}
        try:
            result = original_step(self, action, step_type)
            if not action.startswith("search["):
                self.sim_obs = result[0]
            return result
        finally:
            for key, value in saved.items():
                setattr(self, key, value)

    environment.step = step


def text_client(records, max_requests, inference_path, *, transport=None, api_key=None):
    class OpenRouterClient:
        def __init__(self, model_name, temperature, max_tokens, top_p):
            self.model = model_name
            self.temperature, self.max_tokens, self.top_p = temperature, max_tokens, top_p

        def call(self, prompt, stop=None):
            import httpx

            from .telemetry import record_usage

            if len(records) >= max_requests:
                raise ValueError("Upstream inference request budget exhausted")
            record = {
                "model": self.model,
                "input_tokens": None,
                "output_tokens": None,
                "cost_usd": None,
                "failure": None,
                "max_tokens": self.max_tokens,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "role": "observation_speculator" if self.max_tokens == 100 else "actor",
                **INFERENCE_CONTEXT.get(),
            }
            started = time.perf_counter()
            try:
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                    "top_p": self.top_p,
                    "frequency_penalty": 0.0,
                    "presence_penalty": 0.0,
                }
                # Same parameters as the upstream OpenRouter client, no new prompts.
                with httpx.Client(timeout=60, transport=transport) as client:
                    response = client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": "Bearer "
                            + (api_key or os.environ["OPENROUTER_API_KEY"])
                        },
                        json=payload,
                    )
                    response.raise_for_status()
                    body = response.json()
                record.update(
                    generation_id=body.get("id"),
                    provider=body.get("provider"),
                    model_returned=body.get("model"),
                )
                record_usage(
                    record, body.get("usage", {}), "prompt_tokens", "completion_tokens", None, None
                )
                details = body.get("usage", {}).get("completion_tokens_details", {})
                record["reasoning_tokens"] = (
                    details.get("reasoning_tokens") if isinstance(details, dict) else None
                )
                record["finish_reason"] = body["choices"][0].get("finish_reason")
                result = body["choices"][0]["message"]["content"]
                record["visible_output_chars"] = len(result) if isinstance(result, str) else 0
                if not isinstance(result, str) or not result.strip():
                    record["failure_reason"] = "empty_visible_response"
                    raise ValueError("Empty upstream model response")
                return result
            except Exception as exc:
                record["failure"] = type(exc).__name__
                raise ValueError(f"Upstream inference failed: {type(exc).__name__}") from None
            finally:
                record["latency_s"] = time.perf_counter() - started
                records.append(record)
                with inference_path.open("a") as stream:
                    stream.write(json.dumps(record) + "\n")

    return OpenRouterClient


def run(args):
    indices = paper_indices(args.count)
    root = prepare(args.source)
    if args.prepare_only:
        return {"source": str(root), "indices": indices, "prepared": True}
    if args.output.exists():
        raise ValueError("Choose a fresh output directory")
    if args.max_requests <= 0 or args.width not in (1, 3):
        raise ValueError("Use a positive request budget and width 1/3")
    from .experiments import source_hashes
    from .paper_collect import collect
    from .paper_reproduction import report_collection

    backend = getattr(args, "backend", "http")
    output = args.output.resolve()
    # The shared collector supplies the tested pre-tool state isolation, actual
    # reset indices, failed-episode evidence and authoritative timing capture.
    # This entry point never prepares forecasts or invokes quota admission.
    config = {
        "protocol": "Single-agent upstream HotpotQA agreement reproduction; no quotas/Jev",
        "actor": args.actor,
        "speculator": args.speculator,
        "width": args.width,
        "backend": backend,
        "indices": indices,
        "max_steps": 7,
        "source_sha256": source_hashes(),
        "upstream": json.loads((root / "upstream.json").read_text()),
        "transport": "Original OpenRouter request parameters and original prompts",
        "compatibility_fixes": [
            "Forward task idx through HistoryWrapper.reset",
            "Isolate hypothetical state and simulate local actions from pre-tool state",
            "Fail incomplete generation episodes rather than misaligning step timings",
            "Retain all authoritative tool retry time",
        ],
        "candidate_width": "Preserve raw upstream output; report strict prefixes and any-match",
        "latency_claim": "None: published HotpotQA result is action agreement, not throughput",
    }
    output.mkdir(parents=True)
    write_json(output / "config.json", config)
    try:
        collect(
            root,
            output / "traces",
            count=args.count,
            actor=args.actor,
            speculator=args.speculator,
            backend=backend,
            max_requests=args.max_requests,
            width=args.width,
            enforce_width=False,
        )
        summary = report_collection(output / "traces", output)
        return {
            key: summary[key]
            for key in (
                "tasks",
                "complete",
                "actual_reset_indices_match",
                "agreement",
                "qa",
                "usage",
                "comparable_to_figure4",
                "reproduction_established",
            )
        }
    except Exception as exc:
        inference = output / "traces/inference.jsonl"
        records = (
            [json.loads(line) for line in inference.read_text().splitlines()]
            if inference.exists()
            else []
        )
        write_json(
            output / "failure.json",
            {
                "type": type(exc).__name__,
                "usage": summarize_inference(records),
                "last_inference": records[-1] if records else None,
            },
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path("data/raw/speculative-action") / REVISION
    )
    parser.add_argument("--output", type=Path, default=Path("results/paper-baseline"))
    parser.add_argument("--actor", default="google/gemini-2.5-flash")
    parser.add_argument("--speculator", default="google/gemini-2.5-flash")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--backend", choices=("http", "mock"), default="http")
    parser.add_argument("--width", type=int, choices=(1, 3), default=3)
    parser.add_argument("--max-requests", type=int, default=512)
    parser.add_argument("--prepare-only", action="store_true")
    print(json.dumps(run(parser.parse_args()), indent=2))


if __name__ == "__main__":
    main()
