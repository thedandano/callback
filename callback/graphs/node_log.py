"""One structured log line when a graph node starts."""

import json
import logging

from callback.models.state import ApplyState, ProfileState


def log_enter(logger: logging.Logger, node: str, state: ApplyState | ProfileState) -> None:
    """Log entry to a node with structured JSON."""
    present = [k for k, v in state.model_dump().items() if v is not None]
    logger.info(json.dumps({"node": node, "session_id": state.session_id, "input_fields": present}))
