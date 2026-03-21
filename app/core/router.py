from app.utils.enums import InputType

# Maps input_type + route hints to tool execution order hints
ROUTE_TOOL_PRIORITIES: dict[str, list[str]] = {
    "log_triage": ["log_analysis", "database_query", "webhook"],
    "email_response": ["email_draft"],
    "ticket_escalation": ["database_query", "webhook", "email_draft"],
    "ticket_triage": ["database_query", "log_analysis"],
    "incident_response": ["log_analysis", "database_query", "pagerduty_incident", "slack_notification"],
    "incident_escalation": ["log_analysis", "database_query", "pagerduty_incident", "slack_notification"],
    "default": ["log_analysis", "database_query"],
}

INPUT_TYPE_DEFAULT_ROUTES: dict[InputType, str] = {
    InputType.LOG: "log_triage",
    InputType.EMAIL: "email_response",
    InputType.TICKET: "ticket_triage",
}


def get_route(task_type: InputType, classification_route: str | None = None) -> str:
    """Returns the canonical route for a classified task."""
    if classification_route and classification_route in ROUTE_TOOL_PRIORITIES:
        return classification_route
    return INPUT_TYPE_DEFAULT_ROUTES.get(task_type, "default")


def get_suggested_tools(route: str) -> list[str]:
    return ROUTE_TOOL_PRIORITIES.get(route, ROUTE_TOOL_PRIORITIES["default"])
