# V1 Evaluation Report

Run date: 2026-09-05. Environment: Python 3.11.5, local deterministic hashing embeddings, offline extractive answer provider, bundled synthetic corpus.

| Metric | Result |
|---|---:|
| Cases | 30 |
| Answerable / should abstain | 25 / 5 |
| Retrieval Hit@5 | 1.00 |
| Citation correctness | 1.00 |
| Correct abstention | 1.00 |
| Failed cases | 0 |

The threshold was changed from `0.12` to `0.20` after the first run incorrectly answered two unrelated questions. On the fixed dataset, the lowest answerable Top-1 score was about `0.296`, while the highest unrelated score was about `0.161`; `0.20` separates these samples.

This controlled change improves the bundled regression set but does not prove general accuracy. A larger real-world evaluation would require held-out public runbooks, human relevance labels, provider-specific generation metrics and confidence intervals.

Reproduce with:

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe .\evals\run_eval.py
```
