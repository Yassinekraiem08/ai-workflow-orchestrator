# Examples

Three realistic scenarios showing the full orchestrator trace: classification → planning → execution → (optional replan) → output.

Each folder contains:
- `input.json` — what you'd POST to `/workflows/submit`
- `trace.json` — the full run trace (steps, outputs, LLM calls, cost)

## Scenarios

| Folder | Input type | Route | Key feature shown |
|--------|-----------|-------|-------------------|
| [`log_incident/`](log_incident/) | log | `log_triage` | Multi-step plan + dynamic replan |
| [`ticket_escalation/`](ticket_escalation/) | ticket | `ticket_escalation` | Human-in-the-loop escalation |
| [`email_response/`](email_response/) | email | `email_response` | Fast single-tool execution + quality score |

## Run an example

```bash
# Start the stack
docker compose up

# Get a token
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "X-API-Key: dev-key-changeme" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Submit the example
curl -X POST http://localhost:8000/workflows/submit \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @examples/log_incident/input.json

# Watch the live trace
curl -N -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/workflows/<run_id>/stream
```
