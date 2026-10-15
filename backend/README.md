# Support workspace API package

Python 3.12 backend for the [support copilot workspace](https://github.com/firedrill-tools/support-copilot-workspace). The full repository also contains its Next.js/CopilotKit frontend.

```sh
uv sync --dev --locked
uv run support-workspace-api --list-cases
uv run support-workspace-api --init-case starter --workspace workspace.json
OPENAI_API_KEY=... uv run support-workspace-api --workspace workspace.json
```

The API listens on `127.0.0.1:8123`. OpenAI is required for normal chat; listing/reset needs no key. `OPENAI_MODEL` and `OPENAI_BASE_URL` select the actual model endpoint. Each fresh file is private and initialization refuses overwrite. Only operator approval commits a synthetic refund; no payment processor is connected. Run one process/worker per file.

`AgentRuntime` owns native clients/checkpoints within an async context, and supplies `invoke`/`ainvoke` with caller thread/run IDs. `build_agent` accepts explicitly caller-owned model/checkpointer dependencies. ASGI lifespan opens and closes its own runtime. Business records and raw/SDK observations remain in JSON after shutdown; conversations in MemorySaver do not.

Verify with `uv run --no-sync pytest -q`, `uv build`, and `uv run --no-sync python ../scripts/check_package.py` from the repository. The wheel and source archive include the same eight hash-bound inputs. The source archive can also list/initialize them without the parent checkout. Full UI, scenario and proof documentation is in the repository's root README. Live provider quality, publication/license and the new Firedrill integration remain unverified.
