import unittest
from types import SimpleNamespace

import requests

from quota_spec.capture_bank import generation_span
from quota_spec.wiki_http import USER_AGENT, WikiHTTP


class WikiHTTPTests(unittest.TestCase):
    def test_identified_client_paces_requests_and_honors_retry_after(self):
        now = [0.0]
        seen = []
        responses = []
        for status in (429, 200, 200):
            r = requests.Response()
            r.status_code = status
            r.headers["Retry-After"] = "3"
            responses.append(r)

        def get(*args, **kwargs):
            seen.append((now[0], kwargs))
            return responses.pop(0)

        def sleep(delay):
            now[0] += delay

        http = WikiHTTP(get, interval_s=1, clock=lambda: now[0], sleep=sleep)
        http.begin()
        http.get("https://en.wikipedia.org/")
        http.get("https://en.wikipedia.org/")
        self.assertEqual([t for t, _ in seen], [0.0, 3.0, 4.0])
        self.assertTrue(all(k["headers"]["User-Agent"] == USER_AGENT for _, k in seen))
        self.assertEqual(http.local.backoff_s, 3)
        self.assertEqual(http.local.pacing_s, 1)
        self.assertEqual(http.local.attempts, 3)

    def test_mutex_wait_is_collection_queue_not_native_service(self):
        now = [0.0]

        class ContendedLock:
            def __enter__(self):
                now[0] += 3.0

            def __exit__(self, *args):
                pass

        def get(*args, **kwargs):
            now[0] += 0.2
            response = requests.Response()
            response.status_code = 200
            return response

        http = WikiHTTP(
            get,
            interval_s=1,
            clock=lambda: now[0],
            sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
        )
        http.lock = ContendedLock()
        http.next_submit = 5.0
        http.begin()
        http.get("https://en.wikipedia.org/")
        self.assertAlmostEqual(now[0], 5.2)
        self.assertAlmostEqual(http.local.pacing_s, 5.0)
        self.assertAlmostEqual(http.local.mutex_s, 3.0)
        self.assertAlmostEqual(now[0] - http.local.pacing_s, 0.2)
        self.assertAlmostEqual(http.local.network_s, 0.2)

    def test_client_does_not_retry_access_denial(self):
        r = requests.Response()
        r.status_code = 403
        calls = []

        def get(*args, **kwargs):
            calls.append(1)
            return r

        http = WikiHTTP(get)
        with self.assertRaises(requests.HTTPError):
            http.get("https://en.wikipedia.org/")
        self.assertEqual(len(calls), 1)

    def test_tape_duration_includes_failed_service_and_retry_backoff_not_queue(self):
        prior = {
            "id": "failed",
            "kind": "model",
            "episode": "a",
            "branch": "actor",
            "step": 1,
            "input": "prompt",
            "status": "failed",
            "request_id": 1,
            "ready_s": 0,
            "start_s": 0,
            "end_s": 3,
            "service_s": 3,
            "transport_service_s": 0.25,
        }
        good = {
            **prior,
            "id": "good",
            "status": "completed",
            "request_id": 2,
            "ready_s": 3.2,
            "start_s": 3.2,
            "end_s": 4,
            "service_s": 0.8,
            "transport_service_s": 0.8,
        }
        generation = {"input": "generation", "ready_s": 4.05}
        store = SimpleNamespace(
            nodes=[prior, good], by_id={"good": good}, blob=lambda key: {"attempts": ["good"]}
        )
        self.assertAlmostEqual(generation_span(store, generation), 1.3)


if __name__ == "__main__":
    unittest.main()
