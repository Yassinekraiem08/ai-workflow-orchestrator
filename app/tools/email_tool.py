from typing import Any, ClassVar

from pydantic import BaseModel, EmailStr

from app.tools.base import BaseTool, ToolResult
from app.utils.helpers import ms_since, utcnow


class EmailDraftInput(BaseModel):
    to_address: str = "customer@example.com"
    subject: str = "Re: Your Support Request"
    context: str
    tone: str = "professional"  # professional, urgent, friendly
    include_escalation_note: bool = False


class EmailDraftTool(BaseTool):
    name: ClassVar[str] = "email_draft"
    description: ClassVar[str] = (
        "Generates a draft email response based on context, recipient, subject, and tone. "
        "Returns subject line, body, and metadata. Does not actually send the email."
    )
    input_schema: ClassVar[type[BaseModel]] = EmailDraftInput

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        start = utcnow()
        try:
            args = EmailDraftInput(**arguments)
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output={},
                error=f"Invalid arguments: {e}",
                latency_ms=0,
            )

        greeting = _get_greeting(args.tone)
        closing = _get_closing(args.tone)
        escalation = (
            "\n\nThis matter has been escalated to our senior support team who will follow up within 2 hours."
            if args.include_escalation_note else ""
        )

        body = (
            f"{greeting},\n\n"
            f"Thank you for reaching out. Regarding your inquiry: {args.context}\n"
            f"{escalation}\n\n"
            f"{closing},\n"
            f"Support Team"
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            output={
                "to": args.to_address,
                "subject": args.subject,
                "body": body,
                "tone": args.tone,
                "word_count": len(body.split()),
                "draft_status": "ready_to_send",
            },
            latency_ms=ms_since(start),
        )


def _get_greeting(tone: str) -> str:
    return {"urgent": "URGENT - Dear Customer", "friendly": "Hi there", "professional": "Dear Customer"}.get(
        tone, "Dear Customer"
    )


def _get_closing(tone: str) -> str:
    return {"urgent": "Urgent regards", "friendly": "Best", "professional": "Best regards"}.get(
        tone, "Best regards"
    )
