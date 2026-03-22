from enum import Enum


class InputType(str, Enum):
    TICKET = "ticket"
    EMAIL = "email"
    LOG = "log"


class RunStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    NEEDS_REVIEW = "needs_review"
    SAFETY_BLOCKED = "safety_blocked"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ToolName(str, Enum):
    LOG_ANALYSIS = "log_analysis"
    EMAIL_DRAFT = "email_draft"
    WEBHOOK = "webhook"
    DATABASE_QUERY = "database_query"
    SLACK_NOTIFICATION = "slack_notification"
    PAGERDUTY_INCIDENT = "pagerduty_incident"
