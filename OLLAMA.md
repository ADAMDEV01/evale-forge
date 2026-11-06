# Running EvalForge with Ollama

EvalForge keeps Demo/Mock evaluations separate from real Ollama evaluations. Mock runs use local demo data and do not call a model. Ollama runs call the configured backend provider and persist the actual responses; provider failures are reported and are never replaced with mock results.

## Install and start Ollama

1. Install Ollama from [ollama.com](https://ollama.com/).
2. Start the Ollama application, or run `ollama serve` in a terminal.
3. Download a model, for example:

   ```powershell
   ollama pull llama3.2
   ```

4. Confirm the model is installed with `ollama list`.

## Configure and run EvalForge

For database initialization, migration, and existing-database adoption guidance, see
[DATABASE.md](./DATABASE.md).

1. Copy `.env.example` to `.env` in the project root.
2. Set `OLLAMA_BASE_URL` to the Ollama server URL, `OLLAMA_MODEL` to an installed model name, and optionally adjust `OLLAMA_TIMEOUT_SECONDS`. The defaults target a local Ollama server. A remote native Ollama server is supported if reachable from the backend.
3. Install project dependencies if needed:

   ```powershell
   npm install
   python -m pip install -r backend/requirements.txt
   ```

4. Start the backend from the project root:

   ```powershell
   python -m uvicorn backend.app.main:app --reload
   ```

5. In another terminal, start the frontend:

   ```powershell
   npm run dev
   ```

6. Open EvalForge, select **Ollama** as the evaluation mode, choose a dataset and evaluation method, then start the evaluation. The UI shows the real model responses and persisted results. The backend checks Ollama connectivity and model availability before processing cases.

`OLLAMA_BASE_URL` is backend-only and is not returned to the frontend. Estimated cost is unavailable unless reliable pricing is explicitly configured.

For production, host Ollama separately and restrict access to the backend over a
private network, VPN, firewall, or authenticated private proxy. Do not expose
the unauthenticated Ollama server port publicly. The current provider sends
native `/api/tags` and `/api/generate` requests and does not implement direct
Ollama Cloud API-key authentication; use a private native Ollama endpoint.
See [DEPLOYMENT.md](./DEPLOYMENT.md) for the recommended architecture.

## Demo/Mock mode

Select **Mock** in the evaluation mode selector. It uses the existing local demo behavior and does not contact Ollama. Mock activity is labeled separately from persisted Ollama runs.

## Automated tests

From the project root:

```powershell
pytest -q backend/tests/
npm run test:run
npm run build
```

Backend provider tests use a mocked HTTP transport; these tests do not require Ollama or external API keys.
