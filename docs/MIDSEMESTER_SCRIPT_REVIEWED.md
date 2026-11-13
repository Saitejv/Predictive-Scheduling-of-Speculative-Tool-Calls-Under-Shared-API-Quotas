# CSE 585 Midsemester Presentation Script

*Timing guide: approximately eight minutes of speaking at 135 words per minute. Slide timestamps exclude transitions; allow about one additional minute for transitions and pauses.*

## Slide 1 — Introduction (0:00–0:20)

Hi everyone, I'm Saitej Velaga, and our group includes Jack McClure and Angela Li. Our project is *Predictive Scheduling of Speculative Tool Calls Under Shared API Quotas*. I'll explain the problem, our approach, what we've built, and what we'll test next.

## Slide 2 — Motivation (0:20–2:05)

Our project builds on the *Speculative Actions* paper we read in class. The paper uses a fast predictor, called the Speculator, to anticipate future actions while a slower model or tool is still working. If the prediction is correct, some work is already underway, reducing waiting time.

That early work is called speculation. It can save time, but it also consumes resources when the prediction is wrong. The paper studies this tradeoff. Our project asks what happens when several agents share the same limited number of API requests.

Suppose Agent A uses the last available request to start a search it might need later. Agent B then asks for a search it definitely needs to continue. B has to wait until more requests become available. If A never needs its search, we've wasted a request and delayed B.

Our quota allows a set number of requests per time window. Once a request starts, finishing or canceling it doesn't give that allowance back. It resets at the next window. So B may have to wait even when the search service is idle.

Even a correct guess can hurt overall performance. As a hypothetical example, saving A half a second would not justify delaying B by three seconds.

We want to predict when starting a search early helps the group. We expect this to matter most when requests arrive in bursts and quota resets take much longer than individual searches.

## Slide 3 — Approach (2:05–4:35)

We've implemented a Python controller that decides whether a speculative search should run. A separate candidate generator proposes one possible search per step from the question and previous results. That generator could use code or a small language model; we haven't finalized that choice. The controller then follows three steps.

First, predict what searches agents might need. We'll compare three alternatives: Jev, Kev, and a history table. With Jev or Kev, we make an AI model call using agents' current progress, recent calls, and results. The model returns probabilities: will an agent need another search, will it match the candidate, and will more searches follow? The history alternative estimates those probabilities from past tasks, without an AI call. All three use timing patterns from development tasks to estimate when searches might happen.

These are guesses based on observed information. During evaluation, the controller cannot peek at future calls recorded in the replay traces, and the history table uses development tasks only.

Second, Python code uses those probabilities and timings to generate several possible scenarios. For each scenario, it calculates what happens if we launch the candidate and what happens if we don't. These are code simulations, not AI calls or actual searches. They track waiting requests, quota refills, and result reuse.

The comparison estimates time saved for one agent versus delays caused to others, including agents predicted to need searches soon. Once quota is spent, cancellation cannot restore it. We limit how far ahead the code looks and how many scenarios it checks to keep decisions fast.

Third, the code launches speculation only if estimated total time saved across agents exceeds decision overhead. It also checks that the estimated rate of additional deadline misses stays below a threshold within that look-ahead period. This does not guarantee deadlines.

If speculation is rejected, the agent can still request that search normally. If launched, its result stays hidden until the agent requests the exact same tool and arguments. The agent then reuses the result or joins the running search without spending quota twice.

## Slide 4 — Current Status (4:35–6:00)

We've implemented the main software needed to run these experiments. Our gateway, built with Python asyncio and FastAPI, receives tool requests, tracks available quota, and gives required requests priority. Searches run over a fixed local collection of HotpotQA documents. We impose the quota ourselves to control the experiment.

We've implemented our controller and simpler policies for comparison: never speculate, speculate when quota is available, or save some quota for required calls. Reserving quota is particularly important because it could protect other agents without paying for predictions.

We also have a version that considers only the requesting agent's time savings. Comparing it with the full controller tests whether accounting for other agents actually helps.

The code can collect task records, connect to Jev and Kev, and repeat experiments. Replay means running scheduling policies against the same recorded tasks, so we can compare their effects under consistent conditions.

So far, we've checked the system using scripted searches and mock model responses. We still need to configure the main QA model, Jev access, and a running Kev server. The software is implemented, but we haven't demonstrated faster real-model tasks or measured effects on answer quality.

## Slide 5 — End Goal (6:00–8:00)

Our remaining work is to collect real model data, compare scheduling policies, and check whether the results hold in live runs.

We'll begin with 10 to 20 tasks to check the setup, then collect 100 to 200 task records. We'll use one set of tasks to choose settings and another to evaluate them. That prevents us from tuning the system on the same tasks used to judge its performance.

We'll compare our controller with the simpler scheduling policies. Separately, we'll keep the controller the same and switch between Jev, Kev, and history to test the forecasting methods. We'll also check whether including progress and recent search history improves predictions.

We'll run one, two, four, and eight agents sharing the same quota. One agent shows what happens without competition from other agents. More agents increase that competition. We'll also vary how closely requests arrive together, how often quota resets, and how accurate predictions are.

We'll measure average completion time and the 95th percentile, which shows how long the slower tasks take. We'll also track waiting for required searches, missed deadlines, unused speculative calls, and the time spent generating candidates and making scheduling decisions. We'll repeat comparisons under matched conditions to check whether differences are consistent.

Smaller live experiments will check answer quality and whether replay reflects real behavior. If a simple quota reserve works just as well, we'll report that too. We want to learn when prediction earns its extra cost.

By December 17th, we plan to deliver the working system, reproducible code, and an eight-page report explaining the findings. Thank you. We're happy to take questions.
