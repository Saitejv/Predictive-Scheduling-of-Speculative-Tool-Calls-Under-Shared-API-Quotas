"""Deterministic BM25 over a checksummed, fixed HotpotQA document subset."""

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path


def tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def sha256_json(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class SearchCorpus:
    def __init__(self, documents):
        self.documents = sorted(documents, key=lambda d: (d["title"], d["text"]))
        self.digest = sha256_json(self.documents)
        self.counts = [Counter(tokens(d["title"] + " " + d["text"])) for d in self.documents]
        self.lengths = [sum(c.values()) for c in self.counts]
        self.average = sum(self.lengths) / max(1, len(self.lengths))
        df = Counter(term for c in self.counts for term in c)
        self.idf = {
            t: math.log(1 + (len(self.documents) - n + 0.5) / (n + 0.5)) for t, n in df.items()
        }
        self.title_tokens = [set(tokens(d["title"])) for d in self.documents]

    @classmethod
    def load(cls, path: Path):
        data = json.loads(path.read_text())
        if data.get("version") != 1:
            raise ValueError("Unsupported corpus version")
        corpus = cls(data["documents"])
        if corpus.digest != data["sha256"]:
            raise ValueError("Corpus checksum mismatch")
        return corpus

    def save(self, path: Path):
        path.write_text(
            json.dumps(
                {"version": 1, "sha256": self.digest, "documents": self.documents},
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )

    def search(self, query, limit=5):
        if (
            not isinstance(query, str)
            or not query.strip()
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 20
        ):
            raise ValueError("Search requires a nonempty query and limit 1..20")
        query_terms = set(tokens(query))
        ranked = []
        for index, (counts, length) in enumerate(zip(self.counts, self.lengths)):
            norm = 1.2 * (0.25 + 0.75 * length / max(1, self.average))
            score = sum(
                self.idf.get(t, 0) * counts[t] * 2.2 / (counts[t] + norm)
                for t in sorted(query_terms)
                if counts[t]
            )
            score += 2 * len(query_terms & self.title_tokens[index])
            if score > 0:
                ranked.append((-score, self.documents[index]["title"], index))
        ranked.sort()
        return [{**self.documents[i], "score": round(-score, 8)} for score, _, i in ranked[:limit]]


def candidate_query(question, results, step):
    """One cheap observed-state proposal. Never consumes answers/support labels."""
    if step == 0:
        return question
    return results[0]["title"] if results else None


def required_query(question, results, previous_queries, step):
    """Scripted retrieval agent: question, mentioned title, then unseen result title."""
    if step == 0:
        return question
    for result in results:
        title = result["title"]
        if title.lower() in question.lower() and title not in previous_queries:
            return title
    return next((r["title"] for r in results if r["title"] not in previous_queries), question)
