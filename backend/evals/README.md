# Zenith evals

Benchmarks for *your* installed models, run against your local Ollama. They
use a throwaway data directory, never your real Zenith data.

```bash
cd backend
python -m evals                                   # all suites
python -m evals agent --model qwen2.5-coder:7b --repeat 3
python -m evals --json report.json -v
```

| Suite | Measures | Needs |
|---|---|---|
| `routing` | Does the router pick the intended role (code / reasoning / quick / general)? Falling back to `general` counts as correct when no model for that role is installed. | Only `ollama list`; no generation |
| `rag` | recall@k: does retrieval return the right document for 8 questions over a 5-document corpus? The header shows whether it ran `hybrid` (vectors) or `lexical`. | An embedding model for hybrid mode (`ollama pull nomic-embed-text`) |
| `agent` | Task success on 5 real tasks in a scratch folder (create/edit files, fix a failing test, count lines, rename a function across files), checked by inspecting the result, not the model's claims. | A tool-capable model. Small (<4B) models usually score low. `--sandbox` runs commands in the docker sandbox. |

Small models are noisy, so use `--repeat 3` or more before comparing models. Add cases to
`evals/data/*.json*` or `AGENT_TASKS` in `__main__.py`. `tests/test_evals_harness.py`
checks that every agent task accepts its reference solution and rejects the unsolved state.
