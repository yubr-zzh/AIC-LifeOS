# LongMemEval-S local data adapter

This directory contains only the adapter documentation and a provenance manifest template. The third-party dataset is not included.

The cleaned LongMemEval-S JSON is pinned to Hugging Face revision `98d7416c24c778c2fee6e6f3006e7a073259d48f` (SHA-256 `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`). Keep the 277 MB source file outside this repository. Copy `manifest.template.json` beside the local dataset as `manifest.json`. The adapter intentionally refuses to read raw dataset files located under the repository, and refuses a mismatched revision or hash.

The upstream format is an array of question records. The adapter exposes question metadata, timestamped haystack sessions and their turns, evidence session IDs, and the abstention marker while retaining each original record in `raw`. Retrieval metrics should exclude abstention cases where no evidence location exists; abstention answer behavior should be measured separately.

Example (PowerShell, after the manifest is configured):

```powershell
python tools/benchmarks/longmemeval_adapter.py 'D:\bench-data\LongMemEval\longmemeval_s_cleaned.json' `
  --manifest 'D:\bench-data\LongMemEval\manifest.json' --smoke 50
```

The smoke subset is selected round-robin across `question_type` strata, with abstention questions in a separate stratum. Selection is deterministic for a fixed input order. The adapter does not call models, score answers, download data, or implement the general evaluation runner.

Run the zero-model lexical session-retrieval baseline after configuring the local manifest:

```powershell
python tools/benchmarks/eval_longmemeval_retrieval.py 'D:\path\outside\repo\longmemeval_s_cleaned.json' `
  --manifest 'D:\path\outside\repo\manifest.json' --smoke 50 -k 5 `
  --output 'D:\path\outside\repo\retrieval-smoke-50.json'
```

Omit `--smoke 50` to evaluate all 500 questions. The report separates evidence-session Recall@K, all-evidence hit rate, MRR/NDCG, and abstention-question retrieval hits. Abstention hits are diagnostic only; answer-level refusal still needs a separately evaluated answerer and fixed judge.

The runner supports `--scorer legacy`, `--scorer hybrid`, and a dependency-free `--scorer bm25` ablation. BM25 currently tokenizes English alphanumeric terms and is an offline benchmark candidate; it has not been integrated into LifeOS runtime retrieval or evaluated on multilingual LifeOS records.

An extractive context-size ablation can compare all turns with user turns only by adding `--turns user`. The report includes character retention/reduction and the same evidence-session metrics. This tests whether removing assistant turns preserves retrieval evidence; it is not a generated summary or a full compression-quality evaluation.

For an exploratory answer-quality smoke test, `prepare_longmemeval_answer_smoke.py` creates a stratified sample with BM25 top sessions and selected salient turns plus neighboring dialogue. It writes model input and gold labels separately; never pass the gold file to the answer-generation prompt. A locally authenticated Codex CLI can generate predictions, and `score_longmemeval_answers.py` scores a separate semantic-judgment JSON. Record the generator and judge model; using the same model for both is exploratory and can bias the result. The official 500-question answer evaluation still requires its fixed judge setup.

Upstream references: [LongMemEval repository](https://github.com/xiaowu0162/LongMemEval) and [cleaned dataset](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned). The upstream repository is MIT-licensed; confirm the selected data revision's terms and record the revision and local file hash before use.
