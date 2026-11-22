"""Success and error reply envelopes shared by every MCP tool."""


def ok(
    session_id: str,
    next_action: str | None = None,
    data: dict | None = None,
    workflow: dict | None = None,
) -> dict:
    """Return a success envelope."""
    env: dict = {"session_id": session_id, "status": "ok"}
    if next_action:
        env["next_action"] = next_action
    if data:
        env["data"] = data
    if workflow:
        env["workflow"] = workflow
    return env


def err(
    stage: str,
    code: str,
    message: str,
    session_id: str | None = None,
    retriable: bool = False,
    data: dict | None = None,
    host_action: str | None = None,
) -> dict:
    """Return an error envelope.

    `data` carries explicit nulls for artifacts that were not produced, so the
    host cannot mistake an absent field for a partial success. `host_action` is
    a machine-readable directive telling the host what to do instead of
    synthesizing the missing output itself.
    """
    error: dict = {
        "stage": stage,
        "code": code,
        "message": message,
        "retriable": retriable,
    }
    if host_action is not None:
        error["host_action"] = host_action
    env: dict = {
        "status": "error",
        "error": error,
    }
    if data is not None:
        env["data"] = data
    if session_id is not None:
        env["session_id"] = session_id
    return env
