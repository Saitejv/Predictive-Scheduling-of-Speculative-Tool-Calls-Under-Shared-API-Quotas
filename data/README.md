# Frozen HotpotQA retrieval workload

Source: [HotpotQA](https://hotpotqa.github.io/), Yang et al., EMNLP 2018.
The dataset and Wikipedia text are distributed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
This subset and its derived traces retain that attribution/license. Search
corpus paragraphs are preserved; duplicate titles keep their first paragraph
in source order. Trace formatting, selection, scripted queries and controlled
timing delays are transformations made for this project.

The original CMU download hostname did not resolve during collection. The
collector used the public `hotpotqa/hotpot_qa`, `distractor`, `validation` mirror
through Hugging Face's datasets server. `manifest.json` records the exact page
URLs, source hashes, original task IDs, corpus checksum and split. The subset is
the first 200 source rows, not a random or representative HotpotQA sample.

- `corpus.json`: 1,991 documents and the checksum enforced by the search loader.
- `development.json`, `evaluation.json`: 100 tasks each, split by hash of original
  task ID before history fitting or parameter tuning.
- `pilot.json`: first 20 development tasks in frozen hash order.
- `observations.jsonl`: observed question/history/excerpts and generated candidates.
- `labels.json`: evaluation-only answers and supporting-title labels.
- `raw/`: ignored source downloads; public URLs are retained in the manifest.

Each scripted agent performs three searches: its question, a mentioned title
from returned documents, then a remaining returned title. The fixed candidate
generator proposes the question at the first step and the previous top result's
title later. Neither function receives gold answers, supporting facts, future
calls, or a task's complete context list. Search sees the shared frozen corpus.
The corpus was constructed from development and evaluation documents, as a
shared retrieval environment, but history fitting never uses evaluation labels.

Collection used actual local search calls, 15 ms controlled think delays and
10 ms controlled service delays. Saved think/service times include observed
runtime and scheduling overhead. For a mismatched candidate, replay currently
uses the current required call's measured duration as its service-time estimate;
this simplification should be replaced by per-query timings for live-model work.
No LLM generated these traces or answers. Three calls per task, fixed retrieval
logic and distractor-source documents limit conclusions about general agents.

Do not rerun collection in this folder to reproduce results: wall-clock timing
will change. The frozen JSON traces and manifest are the reproducibility inputs.

## Timing compatibility after review

The frozen v1 traces retain their original values and checksums. In v1,
incorrect speculative candidates used the required search's measured duration
as an estimate. The current collector benchmarks incorrect candidates separately
after each trajectory and labels new manifests `scripted-retrieval-v2`.
Use a new directory when recollecting; the collector refuses to overwrite an
existing manifested dataset. Small pilot subsets now stay entirely within the
development split, including a 20-task total collection.
