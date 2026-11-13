"""Jev/Kev System One adapters; no external model is called implicitly."""

import asyncio
import json
import os
import time
from dataclasses import replace
from urllib.parse import urlsplit

from .models import nonnegative
from .prediction import bounded_context


class SystemOnePredictor:
    measured_overhead = True

    def __init__(
        self,
        history,
        *,
        base_url,
        model,
        api_key=None,
        context="progress",
        timeout_s=2.0,
        input_usd_per_million=None,
        output_usd_per_million=None,
        transport=None,
        decision_timeout_s=5.0,
    ):
        if input_usd_per_million is None and os.environ.get("QUOTA_INPUT_USD_PER_MILLION"):
            input_usd_per_million = float(os.environ["QUOTA_INPUT_USD_PER_MILLION"])
        if output_usd_per_million is None and os.environ.get("QUOTA_OUTPUT_USD_PER_MILLION"):
            output_usd_per_million = float(os.environ["QUOTA_OUTPUT_USD_PER_MILLION"])
        nonnegative(timeout_s, "timeout_s")
        if not 0 < timeout_s <= 60:
            raise ValueError("timeout_s must be in (0, 60]")
        url = urlsplit(base_url)
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.query
            or url.fragment
            or url.username
            or url.password
        ):
            raise ValueError(
                "base_url must be an HTTP(S) URL without credentials, query or fragment"
            )
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be nonblank")
        if context not in ("task", "history", "progress", "no_history", "no_progress"):
            raise ValueError("Unknown context mode")
        for price in (input_usd_per_million, output_usd_per_million):
            if price is not None:
                nonnegative(price, "token price")
        try:
            __import__("httpx")
        except ImportError as exc:
            raise ValueError("Model adapters require pip install -e '.[live]'") from exc
        nonnegative(decision_timeout_s, "decision_timeout_s")
        if not 0 < decision_timeout_s <= 120:
            raise ValueError("decision_timeout_s must be in (0, 120]")
        self.decision_timeout_s = decision_timeout_s
        self.decision_deadline = None
        self.history, self.base_url, self.model = history, base_url.rstrip("/"), model
        self.api_key, self.context, self.timeout_s = api_key, context, timeout_s
        self.input_price, self.output_price = input_usd_per_million, output_usd_per_million
        self.transport = transport
        self.model_revision = os.environ.get("KEV_REVISION") if model.startswith("kev") else None
        self.records = []

    def begin_decision(self):
        self.decision_deadline = time.perf_counter() + self.decision_timeout_s

    def end_decision(self):
        self.decision_deadline = None

    async def _request(self, payload):
        import httpx

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=self.timeout_s, transport=self.transport) as client:
            endpoint = self.base_url + (
                "/decisions"
                if self.base_url.endswith("/alpha")
                else "/systemone"
                if self.base_url.endswith("/v1")
                else "/v1/systemone"
            )
            async with client.stream("POST", endpoint, json=payload, headers=headers) as response:
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 65536:
                        raise ValueError("Prediction response exceeds 64 KiB")
                return json.loads(content)

    async def _bounded_request(self, payload):
        remaining = (
            self.timeout_s
            if self.decision_deadline is None
            else min(self.timeout_s, self.decision_deadline - time.perf_counter())
        )
        if remaining <= 0:
            raise TimeoutError("Decision inference budget exhausted")
        return await asyncio.wait_for(self._request(payload), timeout=remaining)

    def predict(self, state, agent):
        started = time.perf_counter()
        context = bounded_context(state, agent, self.context)
        questions = {
            "reuse": {
                "type": "noul",
                "instructions": "Conditional on this agent making another required search, will its next search use exactly the candidate tool and arguments?",
            },
            "next": {
                "type": "noul",
                "instructions": "Will this agent need another required search before finishing, excluding any search already queued or running?",
            },
            "continues": {
                "type": "noul",
                "instructions": "After its next future required search (excluding any search already queued or running), will this agent need at least one more search?",
            },
        }
        payload = {"model": self.model, "state": context, "questions": questions}
        record = {
            "task_id": agent.task_id,
            "observed_at_s": state.now_s,
            "model_requested": self.model,
            "model_revision": self.model_revision,
            "context": self.context,
            "input_chars": len(json.dumps(context)),
            "cost_usd": None,
            "input_tokens": None,
            "output_tokens": None,
            "failure": None,
        }
        try:
            if len(json.dumps(payload).encode()) > 65536:
                raise ValueError("Prediction request exceeds 64 KiB")
            response = asyncio.run(self._bounded_request(payload))
            if not isinstance(response, dict):
                raise ValueError("Prediction response must be an object")
            # Retain the complete bounded provider result for frozen replay audits.
            record["response"] = response
            from .telemetry import record_usage

            record_usage(
                record,
                response.get("usage", {}),
                "input_tokens",
                "output_tokens",
                self.input_price,
                self.output_price,
            )
            record.update(
                model_returned=response.get("model"),
                generation_id=response.get("id"),
                provider=response.get("provider"),
            )
            if not isinstance(response.get("answers"), dict):
                raise ValueError("Prediction response must contain an answers object")
            answers = response["answers"]
            base = self.history.predict(state, agent)
            prediction = replace(
                base,
                reuse_probability=answers["reuse"]["noul"],
                next_probability=answers["next"]["noul"],
                continue_probability=answers["continues"]["noul"],
            )
            return prediction
        except Exception as exc:
            record["failure"] = type(exc).__name__
            record["http_status"] = getattr(getattr(exc, "response", None), "status_code", None)
            raise ValueError(f"{self.model} prediction failed: {type(exc).__name__}") from exc
        finally:
            record["latency_s"] = time.perf_counter() - started
            self.records.append(record)


class JevPredictor(SystemOnePredictor):
    def __init__(self, history, **kwargs):
        key = kwargs.pop("api_key", None) or os.environ.get("TYPESAFE_API_KEY")
        if not key:
            raise ValueError("Jev unavailable: set TYPESAFE_API_KEY")
        super().__init__(
            history,
            api_key=key,
            base_url=kwargs.pop("base_url", None)
            or os.environ.get("JEV_BASE_URL", "https://api.typesafe.ai"),
            model=kwargs.pop("model", None) or os.environ.get("JEV_MODEL", "jev-latest"),
            **kwargs,
        )


class KevPredictor(SystemOnePredictor):
    def __init__(self, history, **kwargs):
        endpoint = kwargs.pop("base_url", None) or os.environ.get("KEV_BASE_URL")
        if not endpoint:
            raise ValueError("Kev unavailable: set KEV_BASE_URL to your pinned pretrained server")
        super().__init__(
            history,
            base_url=endpoint,
            model=kwargs.pop("model", None) or os.environ.get("KEV_MODEL", "kev-latest"),
            api_key=kwargs.pop("api_key", None) or os.environ.get("KEV_API_KEY"),
            **kwargs,
        )
        self.model_revision = os.environ.get("KEV_REVISION")


class MockSystemOnePredictor(SystemOnePredictor):
    """Exercise the real HTTP serialization/parser without network or credentials.

    Probabilities are fixed fixtures, never measured model predictions.
    """

    measured_overhead = False

    def __init__(self, history, **kwargs):
        import httpx

        def handler(request):
            payload = json.loads(request.content)
            if set(payload["questions"]) != {"reuse", "next", "continues"}:
                return httpx.Response(400)
            return httpx.Response(
                200,
                json={
                    "model": "mock-system-one",
                    "answers": {
                        "reuse": {"type": "noul", "noul": 0.75},
                        "next": {"type": "noul", "noul": 1.0},
                        "continues": {"type": "noul", "noul": 0.5},
                    },
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            )

        super().__init__(
            history,
            base_url="http://mock.invalid",
            model="mock-system-one",
            transport=httpx.MockTransport(handler),
            **kwargs,
        )


class KevSpacePredictor(KevPredictor):
    """Explicit public-demo backend. Retain queue/network AND GPU service timing.

    The Space revision identifies its code, not a guaranteed loaded weight hash.
    This exploratory route must not be reported as the pinned local server.
    """

    def __init__(self, history, **kwargs):
        super().__init__(
            history,
            base_url="https://jaredpalmer-kev.hf.space",
            model="jaredpalmer/kev-0.8b",
            **kwargs,
        )
        self.model_revision = "unverified-loaded-weights; public Space"

    async def _request(self, payload):
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout_s, transport=self.transport) as client:
            base = self.base_url + "/gradio_api/call/decide"
            response = await client.post(
                base,
                json={
                    "data": [
                        json.dumps(payload["state"]),
                        json.dumps(payload["questions"]),
                        "Kev-0.8B",
                        True,
                        False,
                        False,
                        4,
                    ]
                },
            )
            response.raise_for_status()
            event = response.json()["event_id"]
            async with client.stream("GET", base + "/" + event) as response:
                response.raise_for_status()
                event_type = None
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        event_type = line[7:]
                    elif line.startswith("data: "):
                        data = json.loads(line[6:])
                        if event_type == "error":
                            raise ValueError("Kev Space rejected inference: " + str(data)[:300])
                        if event_type == "complete":
                            result = data[1]
                            if not isinstance(result, dict):
                                raise ValueError("Invalid Kev Space response")
                            return result
            raise ValueError("Kev Space ended without a prediction")
