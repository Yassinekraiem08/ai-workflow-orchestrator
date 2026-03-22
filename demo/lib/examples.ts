import type { InputType } from "./types";

export interface Example {
  label: string;
  input_type: InputType;
  raw_input: string;
  priority: number;
}

export const EXAMPLES: Example[] = [
  {
    label: "P1 Outage Ticket",
    input_type: "ticket",
    priority: 1,
    raw_input: `TICKET-9841 [P1 / CRITICAL]
Title: Payment service returning 503 for all EU customers
Reporter: ops-on-call@company.com
Opened: 2026-03-22 02:17 UTC

Description:
Since 02:12 UTC the /api/v2/checkout endpoint returns 503 for 100% of requests
originating from EU-WEST-1. US-EAST-1 is unaffected. Revenue impact estimated
at $12,000/min. No recent deploys in the last 6 hours.

Logs snippet:
[02:12:03] ERROR  payment-svc: upstream connect error: connection refused
[02:12:03] ERROR  payment-svc: circuit breaker OPEN on dependency: fraud-check-svc
[02:12:04] WARN   gateway: retrying 503 from payment-svc (attempt 1/3)
[02:12:07] ERROR  gateway: all retries exhausted, returning 503 to client`,
  },
  {
    label: "Angry Customer Email",
    input_type: "email",
    priority: 4,
    raw_input: `From: david.chen@gmail.com
To: support@company.com
Subject: URGENT — charged twice and no response for 5 days

Hello,

I was charged $149.99 twice on March 17th (order #ORD-28847). I have emailed
three times and opened two chat sessions — nobody has resolved this.

I am deeply frustrated. I run a small business and that double-charge has
caused my account to dip below minimum balance, triggering overdraft fees.
I need a full refund of $149.99 plus $35 in bank fees within 24 hours or I
will dispute the charge with my card issuer and file a BBB complaint.

Please escalate this immediately.

David Chen`,
  },
  {
    label: "DB Connection Storm",
    input_type: "log",
    priority: 2,
    raw_input: `2026-03-22 03:00:01 INFO  app-worker-03: Starting scheduled report generation
2026-03-22 03:00:02 ERROR app-worker-03: DB pool exhausted — waiting for connection (attempt 1)
2026-03-22 03:00:05 ERROR app-worker-03: DB pool exhausted — waiting for connection (attempt 2)
2026-03-22 03:00:08 ERROR app-worker-03: DB pool exhausted — waiting for connection (attempt 3)
2026-03-22 03:00:08 ERROR app-worker-03: asyncpg.exceptions.TooManyConnectionsError: remaining connection slots are reserved
2026-03-22 03:00:08 CRITICAL app-worker-03: Report generation failed — task aborted
2026-03-22 03:00:09 WARN  celery-beat: Task report.generate retried (1/3)
2026-03-22 03:00:12 ERROR app-worker-04: asyncpg.exceptions.TooManyConnectionsError: remaining connection slots are reserved
2026-03-22 03:00:12 ERROR app-worker-05: asyncpg.exceptions.TooManyConnectionsError: remaining connection slots are reserved
2026-03-22 03:00:13 CRITICAL db-proxy: max_connections (100) reached — rejecting all new connections`,
  },
];
