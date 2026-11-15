"""Persistent-loop Jev HTTP pooling; identical payloads and bounded requests."""

import asyncio
import concurrent.futures
import threading

from .adapters import JevPredictor


class JevHTTPPool:
    def __init__(self, *, connections=4, transport=None):
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.closed = False
        self.client = None
        self.error = None

        def serve():
            import httpx

            asyncio.set_event_loop(self.loop)
            try:
                self.client = httpx.AsyncClient(
                    transport=transport,
                    limits=httpx.Limits(
                        max_connections=connections,
                        max_keepalive_connections=connections,
                        keepalive_expiry=60,
                    ),
                )
            except Exception as exc:
                self.error = exc
            finally:
                self.ready.set()
            if self.error is None:
                self.loop.run_forever()
            self.loop.close()

        self.thread = threading.Thread(target=serve, name="jev-http-pool", daemon=True)
        self.thread.start()
        if not self.ready.wait(10):
            raise TimeoutError("Jev HTTP pool did not initialize")
        if self.error:
            raise self.error

    def infer(self, predictor, payload):
        if self.closed:
            raise ValueError("Jev pool is closed")
        future = asyncio.run_coroutine_threadsafe(predictor._bounded_request(payload), self.loop)
        try:
            return future.result(timeout=predictor.timeout_s + 1)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError("Pooled Jev request exceeded total deadline") from None

    def close(self):
        if self.closed:
            return
        self.closed = True
        future = asyncio.run_coroutine_threadsafe(self.client.aclose(), self.loop)
        try:
            future.result(timeout=5)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=5)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class PooledJevPredictor(JevPredictor):
    def __init__(self, history, *, pool, **kwargs):
        self.pool = pool
        super().__init__(history, **kwargs)

    async def _request(self, payload):
        return await self._request_with_client(self.pool.client, payload)

    def _infer(self, payload):
        return self.pool.infer(self, payload)
