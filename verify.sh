#!/bin/bash
BASE="http://ai-workflow-orch-prod-alb-851576625.us-east-1.elb.amazonaws.com"
KEY="my-prod-key-2026"

TOKEN=$(curl -s -X POST "$BASE/auth/token" -H "X-API-Key: $KEY" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "Token: $TOKEN"

RUN=$(curl -s -X POST "$BASE/workflows/submit" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"input_type":"ticket","raw_input":"Production database is throwing connection pool exhaustion errors every 5 minutes. P1 incident affecting all users.","priority":9}')
echo "Submitted: $RUN"

RUN_ID=$(echo "$RUN" | python3 -c "import sys,json; print(json.load(sys.stdin)['run_id'])")
echo "Run ID: $RUN_ID"

echo "Polling..."
for i in $(seq 1 30); do
  sleep 4
  STATUS=$(curl -s "$BASE/workflows/$RUN_ID" -H "Authorization: Bearer $TOKEN")
  STATE=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  echo "[$i] $STATE"
  if [[ "$STATE" == "completed" || "$STATE" == "failed" || "$STATE" == "dead_letter" ]]; then
    echo "Final result:"
    echo "$STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print('quality_score:', d.get('quality_score')); print('cache_hit:', d.get('cache_hit')); print('safety_flagged:', d.get('safety_flagged')); print('final_output:', (d.get('final_output') or '')[:300])"
    break
  fi
done
