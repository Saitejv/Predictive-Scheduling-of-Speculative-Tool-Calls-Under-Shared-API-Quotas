# HotpotQA capture checkpoint: 50 questions

The requested 20-question validation and expansion to **50 independent questions**
are complete. Each question has a successful sequential and speculative live
episode: 100 episodes in total. The expanded order preserves the original 20
questions as its prefix; the additional 30 were collected without repeating
successful pilot questions. Both actor and observation model were Gemini 2.5
Flash, using the existing pinned prompts/parser and seven-action horizon.

| Captured / completed data | Count |
| --- | ---: |
| Canonical speculative tapes | 50 |
| Independent sequential live episodes | 50 |
| Authoritative state transitions across both modes | 436 |
| Canonical authoritative actions | 214 |
| Complete prediction windows on canonical histories | 151 |
| Ranked candidate actions | 441 |
| Eligible Search candidate ranks with full results/states | 247 |
| Missing eligible Search results | 0 |
| Model stages, including bank completion | 738 |
| Search executions, including completion alternatives | 497 |

The bank preserves each candidate rank, exact query, provisional observation,
hypothetical actor output, authoritative history, full WikiEnv state and tool
result. Used and unused speculative results are captured. Request settings,
responses, tokens, costs, errors, local queue time and measured service time
are retained per attempt. Service includes network/provider waiting. Actual
elapsed spans are also saved, while simulator durations exclude local collection
pacing. The 150.148-second actor service outlier remains in the data.

Live canonical answer EM was 44%; 13 of 50 speculative episodes hit the action
limit and force-finished. Successful capture means execution and evidence are
complete, not that every question was answered correctly. Frozen scheduling
holds those outputs fixed and provides no new answer-quality claim.

## Artifacts

- `results/hotpot-dataset-50/`: verified, self-contained scheduling tapes and
  nested live/completion capture stores; `dataset-manifest.json` hashes all inputs.
- `results/hotpot-capture-report-50/`: coverage/timing/cost report, socket-blocked
  validation and account reconciliation.
- `results/hotpot-predictor-inputs-50/`: 3,378 exact unique contexts across five
  modes, 4,695 case references, and an exploratory 20/30 development/evaluation
  split. The progress mode has 939 unique contexts.
- `results/hotpot-shared-quota-50/`: one-seed 1/2/4/8-worker smoke study with no
  speculation, current capacity and fixed reserve.
- `results/hotpot-dataset-20/` and `results/hotpot-replay-validation-20/`: the
  pilot bank and its validation before expanding the workload.

Source live runs are `hotpot-capture-pilot-20-retry` (seven complete pairs were
selected into `hotpot-capture-pilot-complete-7`),
`hotpot-capture-pilot-remaining-13`, and `hotpot-capture-expansion-30` under
`results/`. Complete alternative banks are `hotpot-bank-pilot-7`,
`hotpot-bank-pilot-13` and `hotpot-bank-expansion-30`.

## Validation

All 436 authoritative state transitions were restored and re-executed with pinned
WikiEnv behavior, and all 436 authoritative prompts were checked. Recorded stage
DAG timing reconstructs within 1 microsecond. Socket-blocked matched replay
verified all 50 saved answers under each policy at 1/2/4/8 workers, checked every
quota window and worker limit, and verified the context hashes and disjoint task
splits. No-quota matched speculative replay produced 16 hits on the completed
bank; this is a counterfactual schedule, distinct from observed live hits.

170 tests passed with no skips. Ruff lint and formatting passed for 64 Python
files. The original paid 20-question summary still reproduces exactly, and all
118 protected older evidence files remain unchanged.

The scheduling engine now maintains one shared quota across a continuous stream
of questions. A worker starts its next question only after its prior question
drains all started work. Required Search calls retain FIFO priority. Exact cache
reuse is per question/agent. Model serving concurrency is assumed unlimited with
fixed recorded single-agent service durations. The smoke study is a mechanics
check, not a Jev/Kev result or a tuned throughput claim.

## Cost and interruptions

Known incremental collection cost, including successful calls in aborted attempts,
was **$0.396111**. Account usage increased by the same amount to floating-point
precision. Two early attempts stopped after a timeout and an upstream 429;
their individual failed-request costs remain unknown in raw logs. Those original
runs are retained rather than silently rewritten or discarded. Complete pair
selection avoids paying again for the seven retained pairs. The subsequent
paced 13- and 30-question runs completed without unknown charges. Alternative
completion costs are separate from live timings.

## Next integration

The data is ready for history/Jev/Kev forecasting. No Jev/Kev calls have been made.
Start with the progress context on development questions, validate both services,
then freeze outputs keyed by exact context/model/settings with measured latency
and cost. Use the same bank for full cross-agent versus own-agent admission.
The prepared contexts explicitly use the existing phase-entry `elapsed=0`
approximation. Extend coverage before claiming adaptive elapsed-time forecasts.
Keep all tuning on the 20-question development split; the 30-question expansion
is exploratory, not fresh confirmation after tuning.

[CAPTURE_REPLAY.md](CAPTURE_REPLAY.md) gives the complete commands and assumptions.
The tracked `CAPTURE_50_MANIFEST.json` identifies the local evidence bundle;
large results and archives remain Git-ignored and must be retained separately.
