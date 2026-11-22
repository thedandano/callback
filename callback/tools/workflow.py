"""Host-facing workflow guidance shared by the apply tools."""

NEXT_EXTRACT_KEYWORDS = "extract_keywords"
NEXT_ONBOARD_RESUME_FIRST = "onboard_resume_first"
NEXT_FETCH_WIKI_THEN_TAILOR = "fetch_wiki_then_tailor"
NEXT_ADD_STORY_FIRST = "add_story_first"


def workflow(
    phase: str,
    next_tool: str | None,
    host_task: str,
    required_input: dict,
    allowed_next_tools: list[str] | None = None,
) -> dict:
    """Build host-facing workflow guidance for the next MCP handoff."""
    workflow = {
        "phase": phase,
        "next_tool": next_tool,
        "host_task": host_task,
        "required_input": required_input,
    }
    if allowed_next_tools:
        workflow["allowed_next_tools"] = allowed_next_tools
    return workflow


_PASS_2_TASK = (
    "First run pass 2 of keyword extraction: start a fresh subagent and give it exactly "
    "data.responsibilities_protocol and load_jd's data.jd_text, word for word, and nothing "
    "else. It returns a key_responsibilities list; send that list to submit_responsibilities. "
    "If you cannot start a subagent, skip pass 2. Then: "
)


def submit_keywords_workflow(
    session_id: str,
    next_action: str,
    orphaned_required: list[str],
    *,
    pass_2_pending: bool = True,
) -> dict:
    if next_action == NEXT_ONBOARD_RESUME_FIRST:
        return workflow(
            phase="onboard_resume",
            next_tool="onboard_user",
            host_task=(
                "Tailoring needs onboarded resume sections and profile wiki context. "
                "Call onboard_user, compile the profile, then restart this job flow "
                "with load_jd using the same job description."
            ),
            required_input={
                "resume_path": "<path to PDF, DOCX, TXT, or Markdown resume>",
                "skills_path": "<optional path to skills file>",
                "accomplishments_path": "<optional path to accomplishments file>",
            },
        )
    if next_action == NEXT_ADD_STORY_FIRST:
        return workflow(
            phase="story_evidence",
            next_tool="create_story",
            host_task=(
                "Collect or create truthful story evidence for orphaned required "
                "keywords before tailoring. After create_story and compile_profile, "
                "restart this job flow with load_jd using the same job description."
            ),
            required_input={
                "primary_skill": (
                    orphaned_required[0] if orphaned_required else "<required keyword>"
                ),
                "skills": orphaned_required or ["<required keyword>"],
                "story_type": "STAR",
                "job_title": "<role title for the evidence>",
                "situation": "<truthful situation>",
                "behavior": "<truthful actions taken>",
                "impact": "<truthful quantified or concrete outcome>",
            },
        )
    tailor_task = (
        "Use data.sections, data.score_gap, data.wiki_index, and "
        "data.tailor_instructions to choose relevant wiki pages and prepare "
        "honest SectionMap edits. Map keywords to evidenced experience that "
        "addresses the employer's problems; leave unsupported gaps uncovered. "
        "If the index already contains enough evidence, submit_tailor is also valid."
    )
    if pass_2_pending:
        return workflow(
            phase="tailor_evidence",
            next_tool="submit_responsibilities",
            allowed_next_tools=["submit_responsibilities", "get_wiki_pages", "submit_tailor"],
            host_task=_PASS_2_TASK + tailor_task,
            required_input={
                "session_id": session_id,
                "key_responsibilities": ["<term from pass 2>"],
            },
        )
    pass_2_tailor_task = (
        "Use data.sections, data.score_gap, data.wiki_index, and "
        "data.tailor_instructions from the submit_keywords reply, plus the keywords "
        "returned here. Treat key_responsibilities as the employer's problems to solve "
        "first; map only keywords backed by dated experience, project evidence, or wiki "
        "stories; leave unsupported gaps uncovered — do not invent facts or keyword-stuff. "
        "Choose relevant wiki pages and prepare honest SectionMap edits. "
        "If the index already contains enough evidence, submit_tailor is also valid."
    )
    return workflow(
        phase="tailor_evidence",
        next_tool="get_wiki_pages",
        allowed_next_tools=["get_wiki_pages", "submit_tailor"],
        host_task=pass_2_tailor_task,
        required_input={
            "session_id": session_id,
            "page_ids": ["experience/<page-id>.md"],
        },
    )


def complete_workflow() -> dict:
    return workflow(
        phase="complete",
        next_tool=None,
        host_task="Return the artifact paths, score report, and outcome to the user.",
        required_input={},
    )
