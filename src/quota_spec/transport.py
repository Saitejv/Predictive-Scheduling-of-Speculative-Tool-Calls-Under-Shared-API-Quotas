"""Async OpenRouter transport with concurrent request/dollar reservations."""

import asyncio
import json
import math
import time

from .artifacts import append_json
from .capture import ACTIVE_CAPTURE
from .telemetry import record_usage


class OptionalExpired(Exception):
    """Unsent optional inference lost its owner while waiting for capacity."""


class InvalidProviderResponse(ValueError):
    """Transient provider/gateway response cannot be used as model output."""


class LiveChat:
    """Atomic reservation of concurrent request costs, with full response evidence."""

    def __init__(
        self,
        client,
        key,
        prices,
        output,
        events,
        max_usd,
        max_requests,
        actor,
        speculator,
        min_request_interval_s=0.0,
        draft_actor=None,
        reserve_unknown_cost=False,
        optional_allowed=None,
    ):
        self.client, self.key, self.prices = client, key, prices
        self.output, self.events = output, events
        self.max_usd, self.max_requests = max_usd, max_requests
        self.actor, self.speculator = actor, speculator
        self.draft_actor = draft_actor or actor
        self.reserve_unknown_cost = reserve_unknown_cost
        self.optional_allowed = optional_allowed
        self.lock, self.semaphore = asyncio.Lock(), asyncio.Semaphore(4)
        # Leave one of the four serving slots available to authoritative work.
        # Waiting optional calls must not acquire a global slot first.
        self.optional_semaphore = asyncio.Semaphore(3)
        self.spent = self.reserved = self.requests = 0
        self.unknown = False
        self.records = []
        if not math.isfinite(min_request_interval_s) or min_request_interval_s < 0:
            raise ValueError("Request interval must be finite and nonnegative")
        self.min_request_interval_s = min_request_interval_s
        self.rate_lock = asyncio.Lock()
        self.next_submit = 0.0

    async def call(self, prompt, role, episode, step):
        queued_at = time.perf_counter()
        if role == "actor":
            return await self._call(prompt, role, episode, step, queued_at)
        self._check_optional(role, episode)
        async with self.optional_semaphore:
            return await self._call(prompt, role, episode, step, queued_at)

    def _check_optional(self, role, episode):
        if role != "actor" and self.optional_allowed and not self.optional_allowed(episode):
            raise OptionalExpired("Unsent draft owner has answered")

    async def _call(self, prompt, role, episode, step, queued_at):
        observation = role == "observation_speculator"
        model = (
            self.speculator
            if observation
            else self.draft_actor
            if role == "speculative_actor"
            else self.actor
        )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1 if observation else 1,
            "max_tokens": 100 if observation else 1000,
            "top_p": 0.9 if observation else 1,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
        }
        price = self.prices[model]
        reserve = (len(json.dumps(payload).encode()) + 4096) * float(price["prompt"]) + payload[
            "max_tokens"
        ] * max(float(price["completion"]), float(price.get("internal_reasoning", 0)))
        async with self.rate_lock:
            delay = max(0.0, self.next_submit - time.perf_counter())
            if delay:
                await asyncio.sleep(delay)
            self.next_submit = time.perf_counter() + self.min_request_interval_s
        async with self.semaphore:
            async with self.lock:
                self._check_optional(role, episode)
                if (
                    self.unknown
                    or not math.isfinite(reserve)
                    or self.spent + self.reserved + reserve > self.max_usd
                    or self.requests >= self.max_requests
                ):
                    raise RuntimeError("Paid request budget exhausted or prior cost unknown")
                self.requests += 1
                request_id = self.requests
                self.reserved += reserve
            self.events.emit(
                "inference_started",
                episode=episode,
                step=step,
                role=role,
                request_id=request_id,
                reserved_usd=reserve,
            )
            started = time.perf_counter()
            queue_s = started - queued_at
            record = {
                "request_id": request_id,
                "episode": episode,
                "step": step,
                "role": role,
                "model": model,
                "cost_usd": None,
                "input_tokens": None,
                "output_tokens": None,
                "failure": None,
            }
            raw = {"request_id": request_id, "request": payload}
            captured = ACTIVE_CAPTURE.get()
            if captured:
                record["capture_node"] = raw["capture_node"] = captured[1]["id"]
            try:
                response = await self.client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": "Bearer " + self.key},
                    json=payload,
                )
                raw["http_status"] = record["http_status"] = response.status_code
                try:
                    body = response.json()
                except ValueError as exc:
                    raw["response_text"] = response.text[:4096]
                    response.raise_for_status()
                    raise InvalidProviderResponse("Provider returned invalid JSON") from exc
                raw["response"] = body
                if not isinstance(body, dict):
                    raise InvalidProviderResponse("Provider response must be an object")
                record_usage(
                    record, body.get("usage", {}), "prompt_tokens", "completion_tokens", None, None
                )
                record.update(
                    provider=body.get("provider"),
                    model_returned=body.get("model"),
                    generation_id=body.get("id"),
                )
                response.raise_for_status()
                try:
                    choice = body["choices"][0]
                    content = choice["message"]["content"]
                except (KeyError, IndexError, TypeError) as exc:
                    raise InvalidProviderResponse("Provider response lacks a choice") from exc
                record.update(
                    finish_reason=choice.get("finish_reason"),
                    visible_output_chars=len(content) if isinstance(content, str) else 0,
                )
                if not isinstance(content, str) or not content.strip():
                    raise InvalidProviderResponse("Empty visible response")
                return content
            except BaseException as exc:
                record["failure"] = type(exc).__name__
                raise
            finally:
                record["latency_s"] = time.perf_counter() - started
                record["queue_s"] = queue_s
                if captured:
                    recorder, node = captured
                    node.update(
                        transport_service_s=record["latency_s"],
                        transport_queue_s=queue_s,
                        request_id=request_id,
                        request=recorder.blob(payload),
                        response=recorder.blob(raw),
                        usage=dict(record),
                    )
                async with self.lock:
                    self.reserved -= reserve
                    if record["cost_usd"] is None:
                        if self.reserve_unknown_cost:
                            self.spent += reserve
                            record["budget_charge_usd"] = reserve
                            record["budget_charge_source"] = "unknown_cost_upper_bound"
                        else:
                            self.unknown = True
                    else:
                        self.spent += record["cost_usd"]
                        record["budget_charge_usd"] = record["cost_usd"]
                if captured:
                    node["usage"] = dict(record)
                self.records.append(record)
                append_json(self.output / "requests.jsonl", raw)
                append_json(self.output / "inference.jsonl", record)
                self.events.emit("inference_finished", **record)
