# Paid-model evaluation run vs the free baseline (2026-10-12)

The same corpus, questions, retrieval and prompts as the committed free-model baseline (`results/quality.json`,
`results/leak.json`, 2026-10-06). The only thing that changes is the model: generators and judge
were reached through a local metered OpenAI-compatible gateway (a budget proxy), using the new `gateway` provider
and the explicit `CLEARANCE_ALLOW_PAID_MODELS=true` opt-in (without it, non-`:free` ids are refused as before). Retrieval is unchanged and
deterministic: local `BAAI/bge-small-en-v1.5` embeddings, pgvector pre-filter + row-level security, top_k 5,
min_score 0.5, recall@5 of the gold document 1.0 for every run.

## What was run

| Run | Generator | Judge | Questions | File |
|---|---|---|---|---|
| Free baseline (existing) | local `qwen3.5:4b` (Ollama) and `nvidia/nemotron-3-super-120b-a12b:free` | `dots-3-note-preview:free` | 54 (49 answerable + 5 unanswerable) | `results/quality.json` |
| Baseline re-judged | same stored answers, nothing re-generated | `claude-opus-5-5` | 54 | `quality-baseline-rejudged-opus.json` |
| Haiku | `claude-haiku-5-5` | `claude-opus-5-5` | 54 (full set) | `quality-haiku.json` |
| Opus, hard subset | `claude-opus-5-5` | `claude-opus-5-5` | 20: the 15 answerable questions that any baseline model or Haiku got wrong, refused or answered unfaithfully, plus the 5 unanswerable ones | `quality-opus-subset.json` |
| Qwen | `qwen3.7-plus` | `claude-opus-5-5` | 54 (full set) | `quality-qwen.json` |
| Qwen smoke (superseded) | `qwen3.7-plus`, max_tokens 150 | `claude-opus-5-5` | 4 requested, 3 answered; q53 was refused by the original 3,000-token Qwen budget, which was raised afterwards | `quality-qwen-smoke.json` |
| Leak test | `claude-haiku-5-5` for Clearance and the unfiltered baseline | n/a (canary string match) | 30 adversarial questions x 11 users = 330 pairs | `leak-haiku.json` |
| Leak test | `qwen3.7-plus` for Clearance and the unfiltered baseline | n/a (canary string match) | the same 330 pairs | `leak-qwen.json` |

Opus is the judge for every row in the comparison, so all generators are graded by one judge.
The original free judge (dots-3) is shown for reference only. Every request is in `calls.jsonl`, summarized in
`calls_summary.json`.

## Full question set (49 answerable + 5 unanswerable)

| Metric | Free: local qwen3.5:4b | Free: nemotron-3-super :free | claude-haiku-5-5 | qwen3.7-plus |
|---|---|---|---|---|
| Correct, original free judge (dots-3) | 42/49 (85.7%) | 37/49 (75.5%) | not run | not run |
| **Correct, Opus judge** (refusals count as wrong) | 43/49 (87.8%) | 44/49 (89.8%) | **47/49 (95.9%)** | 46/49 (93.9%) |
| **Faithful to the passages, Opus judge** | 40/48 (83.3%) | 48/48 (100%) | **48/48 (100%)** | **48/48 (100%)** |
| Faithful, original free judge | 46/48 | 48/48 | not run | not run |
| Key facts present (string check, no judge) | 47/49 | 47/49 | 47/49 | 47/49 |
| False refusals (answerable, said "not available") | 1 (q11) | 1 (q11) | 1 (q11) | 1 (q11) |
| Unanswerable questions declined | 5/5 | 5/5 | 5/5 | 5/5 |
| **Answers with at least one citation** | 48/48 | 47/48 | **48/48** | **48/48** |
| **Answers citing a gold document** | 48/48 | 47/48 | **48/48** | **48/48** |
| Generation latency p50 / p95 | 8.7 s / 12.0 s (CPU) | 3.1 s / 12.1 s | 1.8 s / 2.4 s | 2.5 s / 3.1 s |
| Errors after repair | 0 | 0 (2 re-asked on fallback) | 0 (2 re-asked after transient gateway 403s) | 0 |

## Hard subset (15 answerable + 5 unanswerable), all graded by the Opus judge

| Metric | local qwen3.5:4b | nemotron :free | claude-haiku-5-5 | claude-opus-5-5 | qwen3.7-plus |
|---|---|---|---|---|---|
| Correct | 9/15 | 10/15 | 13/15 | 13/15 | 12/15 |
| Faithful | 11/14 | 14/14 | 14/14 | 14/14 | 14/14 |
| Key facts (string check) | 13/15 | 13/15 | 13/15 | 13/15 | 13/15 |
| Cited a gold document | 14/14 | 13/14 | 14/14 | 14/14 | 14/14 |
| False refusals | 1 | 1 | 1 | 1 | 1 |
| Unanswerable declined | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| Generation latency p50 | 8.8 s | 2.8 s | 1.7 s | 2.8 s | 2.6 s |

The subset was chosen *because* the baseline struggled on it, so the free models' numbers here are biased low by
construction; read it as "what does a stronger model fix", not as an unbiased accuracy estimate.

## Leak test (permission filtering), Haiku and Qwen vs the free baseline generator

| System | Restricted chunk in context | Hidden canary in context | Canary in answer, baseline (`qwen3.5:4b`) | Canary in answer, Haiku | Canary in answer, Qwen 3.7 Plus |
|---|---|---|---|---|---|
| **Clearance** (pre-filter + RLS) | **0/330** | **0/330** | **0/330** | **0/330** | **0/330** |
| RLS only (ablation) | 0/330 | 0/330 | not generated | not generated | not generated |
| Post-filter | 0/330 (100 empty contexts) | 0/330 | not generated | not generated | not generated |
| Unfiltered | 286/330 | 223/330 | 214/330 (64.8%) | 210/330 (63.6%) | 212/330 (64.2%) |

Context-level numbers are identical in all three runs, as expected: filtering does not depend on the model.
Clearance answered "not available to you" in 194 of 330 pairs with the local model, 207 with Haiku and 211 with
Qwen. Without the filter, Qwen leaked by question style in 110/165 direct, 88/132 indirect and 14/33 injection
pairs, almost the same as the baseline's 112, 88 and 14. Post-filter recall at k=5
is unchanged (98.6% vs 96.5%).

## Cost and sample sizes

| Model | Calls (ok / error) | Input / output tokens | Cost | Used for |
|---|---|---|---|---|
| claude-haiku-5-5 | 288 / 55 | 329k / 38k | ≈ $0.05 | 54 quality generations (+2 re-asks), 236 leak-test generations, 1 smoke |
| claude-opus-5-5 | 218 / 11 | 272k / 32k | ≈ $1.74 | 136 re-judgements of stored answers ($1.15: the 96 baseline answers, the 2 Qwen smoke answers and the 48 full-run Qwen answers; identical judge prompts are served from the disk cache and not billed again), 62 judgements of Haiku/Opus/Qwen-smoke answers ($0.44), 20 generations ($0.14) |
| qwen3.7-plus | 290 / 1 | 227,518 / 6,183 | 233,701 of 500,000 tokens | 236 leak-test generations (186,713 tokens), 54 full-set quality generations, 3 earlier smoke generations; one smoke call was refused under the original 3,000-token cap |

Ledger estimates use $0.10/$0.50 (Haiku) and $4/$20 (Opus) per 1M tokens. The proxy's budget endpoint reports
**$1.97 of Anthropic spend** for this project in total, slightly above the ledger's $1.79 because it also counts a few
manual probe calls made outside the harness while debugging. The proxy reports 233,701 Qwen tokens, which matches the
ledger exactly. Errors cost nothing:
- 14 transient `403 Request not allowed` responses from the gateway. Each succeeded when re-run.
- 52 `temperature is deprecated` rejections of judge calls (4 Opus, 48 Haiku). These came from runs where
  temperature was switched on for the Qwen generator, which also applied it to the judge. Those placeholder verdicts
  were discarded, and every Qwen answer was then judged by Opus without temperature.
- 1 Qwen budget refusal under the original cap.

One early Haiku temperature rejection, from before the real runs, was removed from the ledger. No connection
errors occurred: the proxy restart did not hit any call.

## Observations

- **Haiku is the best value here.** Under the same Opus judge it got 47/49 correct, against 46/49 for Qwen 3.7
  Plus, 44/49 for the free nemotron and 43/49 for the local 4B model. It was also 100% faithful, cited a gold document in every answer, and
  was the fastest generator (p50 1.8 s), all for about five cents for the full run. It fixed q33 and q38, which both
  free models got wrong because they left out the location or the "3-year prepaid, 500+ seats" condition on the
  floor price. The local model was also unfaithful on q38: it said the passages gave no floor price.
- **Opus as a generator added nothing on this corpus.** On the 15 hard questions it matched Haiku exactly (13/15,
  with the same two misses) at higher latency and about 40x the price per answer ($0.007 vs $0.00016). It writes fuller answers (it was
  the only model to give the 30-hour cap on q46). Note that it was also its own judge there.
- **Most of the free model's "wrong" answers were a judge effect, not a model one.** Re-judging the stored baseline
  answers with Opus moved nemotron from 75.5% to 89.8% correct. Of its 12 dots-3 misses, 8 were omissions of
  secondary details that Opus accepted. The local model barely moved on correctness (85.7% to 87.8%), but Opus
  marked it unfaithful 8 times where dots-3 had found 2 (for example the "$25 per quarter" quota and the mangled
  floor price). So the free judge made the free cloud model look worse than it was and the local model look more
  faithful than it was. The Opus judge is not perfectly consistent either: the same omission of the 30-hour cap on
  q46 was accepted for Haiku and rejected for nemotron.
- **The two remaining failures are retrieval problems that no model fixes.** In q11 ("which market percentile")
  every model refused, including Opus and Qwen 3.7. The chunk retrieved from the compensation-philosophy document
  is not the paragraph that states the 60th percentile, so refusing was the faithful behaviour. In q14 ("three
  priorities") the top 5 contains Priorities 1 and 2 but not Priority 3. Haiku and Opus said so explicitly and
  did not guess. Document-level recall@5 is 1.0, which hides these chunk-level misses. Next steps would be
  chunk-level gold labels, a larger k, or a re-ranker, not a bigger model.
- **Leakage stays at zero, and the model is not the defence.** With Haiku and with Qwen 3.7 Plus, Clearance
  leaked 0/330 at context level and 0/330 at answer level. With the filter removed, Haiku repeated hidden canaries
  in 210/330 answers and Qwen in 212/330, about the same as the 4B local model (214/330). A stronger model refuses a little more often but does not stop
  repeating restricted content once it is in the context. The permission pre-filter and RLS are what keep it out.
- **Qwen 3.7 Plus is a close second on the full set.** It got 46/49 correct, was 48/48 faithful, cited a gold
  document in every answer and declined all 5 unanswerable questions, with a p50 of 2.5 s. It wrote the tersest
  answers: Qwen used 1,534 output tokens across 57 calls, and Haiku used 4,332 across 52 generations. Its one miss
  beyond the shared q11/q14 failures is the omission type nemotron also makes: on q33 it named the role but not the
  reporting line or the location. One question separates it from Haiku, which is within noise for 49 questions.
  In the leak test it behaves like the other models: 0/330 leaks through Clearance, and 212/330 with the filter
  off.

## Run notes and differences from the baseline

- Sampling: Claude 5.5 models reject the `temperature` parameter, so the new `CLEARANCE_LLM_SEND_TEMPERATURE=false`
  was used and they sampled at their default. The baseline used temperature 0. The full Qwen run used temperature 0
  and `max_tokens` 700, the same as the baseline. The earlier smoke run used `max_tokens` 150.
- The judge prompt and the 4,000-token judge budget are unchanged. Opus judged the Opus-generated answers itself,
  and Haiku/Opus are the same model family, so a same-family bias cannot be ruled out. The judge-free key-fact
  string check, at 47/49 for all four full-set generators, is the cross-check.
- The `retrieval` block in `quality-haiku.json` says 47 questions because it was computed before the two errored
  rows were repaired. All 49 answerable rows are present and hit@5 is true for every one.
- The `seconds` field in `leak-haiku.json` (36 s) is from the last of four runs. The earlier runs stopped on
  transient gateway 403s, and the final run took most generations from the disk cache. Per-call latency is in
  `calls.jsonl`.
- Commands (from the repo root, with `CLEARANCE_GATEWAY_BASE_URL`, `CLEARANCE_GATEWAY_API_KEY`,
  `CLEARANCE_ALLOW_PAID_MODELS=true`, `CLEARANCE_LLM_SEND_TEMPERATURE=false` and
  `CLEARANCE_LLM_LEDGER=results/paid-models/calls.jsonl` set):
  - `clearance eval quality --skip-local --cloud-provider gateway --cloud-model claude-haiku-5-5 --judge-provider gateway --judge-model claude-opus-5-5 --output results/paid-models/quality-haiku.json`
  - `clearance eval quality-repair --path results/paid-models/quality-haiku.json --provider gateway --judge-model claude-opus-5-5 --retry-model claude-haiku-5-5`
  - `clearance eval rejudge --path results/quality.json --output results/paid-models/quality-baseline-rejudged-opus.json --judge-provider gateway --judge-model claude-opus-5-5`
  - `clearance eval quality --skip-local --cloud-provider gateway --cloud-model claude-opus-5-5 --judge-provider gateway --judge-model claude-opus-5-5 --questions q01,q02,q05,q07,q10,q11,q14,q21,q32,q33,q35,q37,q38,q46,q47,q50,q51,q52,q53,q54 --output results/paid-models/quality-opus-subset.json`
  - `CLEARANCE_LLM_SEND_TEMPERATURE=true clearance eval quality --skip-local --cloud-provider gateway --cloud-model qwen3.7-plus ... --output results/paid-models/quality-qwen.json` (temperature on for Qwen; the judge calls in this step failed on temperature, and those placeholder verdicts were dropped), then `clearance eval rejudge --path results/paid-models/quality-qwen.json --output results/paid-models/quality-qwen.json --judge-provider gateway --judge-model claude-opus-5-5`. The smoke file was produced the same way with `--questions q11,q21,q46,q53` and max_tokens 150.
  - `clearance eval leak --generate clearance,unfiltered --provider gateway --model claude-haiku-5-5 --output results/paid-models/leak-haiku.json`
  - `CLEARANCE_LLM_SEND_TEMPERATURE=true clearance eval leak --generate clearance,unfiltered --provider gateway --model qwen3.7-plus --output results/paid-models/leak-qwen.json`. This ran in one pass (686 s, 233 calls, no errors; 3 pairs had an empty context and needed no call), with temperature 0 and max_tokens 700. Qwen calls had a p50 of 2.2 s and a p95 of 4.3 s.
