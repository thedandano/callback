"""Success and error reply envelopes shared by every MCP tool.

Tools return plain dicts (via `ok` / `err`) so FastMCP's output schema stays
unchanged; the models define the shape and the serialization rules in one place.
"""

from pydantic import BaseModel


class OkEnvelope(BaseModel):
    """Success reply. Falsy `next_action` / `data` / `workflow` are left out."""

    session_id: str
    status: str = "ok"
    next_action: str | None = None
    data: dict | None = None
    workflow: dict | None = None

    def to_reply(self) -> dict:
        reply: dict = {"session_id": self.session_id, "status": self.status}
        if self.next_action:
            reply["next_action"] = self.next_action
        if self.data:
            reply["data"] = self.data
        if self.workflow:
            reply["workflow"] = self.workflow
        return reply


class ErrorDetail(BaseModel):
    """The `error` block of an error reply. `host_action` is left out when None."""

    stage: str
    code: str
    message: str
    retriable: bool = False
    host_action: str | None = None

    def to_reply(self) -> dict:
        reply: dict = {
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
            "retriable": self.retriable,
        }
        if self.host_action is not None:
            reply["host_action"] = self.host_action
        return reply


class ErrorEnvelope(BaseModel):
    """Error reply.

    `data` carries explicit nulls for artifacts that were not produced, so the
    host cannot mistake an absent field for a partial success. `data` and
    `session_id` are left out only when None (an empty string or dict is kept).
    """

    status: str = "error"
    error: ErrorDetail
    data: dict | None = None
    session_id: str | None = None

    def to_reply(self) -> dict:
        reply: dict = {"status": self.status, "error": self.error.to_reply()}
        if self.data is not None:
            reply["data"] = self.data
        if self.session_id is not None:
            reply["session_id"] = self.session_id
        return reply


def ok(
    session_id: str,
    next_action: str | None = None,
    data: dict | None = None,
    workflow: dict | None = None,
) -> dict:
    """Return a success envelope."""
    return OkEnvelope(
        session_id=session_id, next_action=next_action, data=data, workflow=workflow
    ).to_reply()


def err(
    stage: str,
    code: str,
    message: str,
    session_id: str | None = None,
    retriable: bool = False,
    data: dict | None = None,
    host_action: str | None = None,
) -> dict:
    """Return an error envelope. `host_action` tells the host what to do instead."""
    detail = ErrorDetail(
        stage=stage, code=code, message=message, retriable=retriable, host_action=host_action
    )
    return ErrorEnvelope(error=detail, data=data, session_id=session_id).to_reply()
