from pathlib import Path

import typst

TEMPLATE_PATH = Path(__file__).parent / "resume_template.typ"


def render_resume(tailored: dict, output_path: str) -> dict:
    """Compile a TailoredResume dict to PDF via Typst.

    Returns {"success": True, "pdf_path": output_path} or
            {"success": False, "error": str}.
    """
    sys_inputs = {k: str(v) for k, v in tailored.items() if v is not None}
    try:
        typst.compile(str(TEMPLATE_PATH), output=output_path, sys_inputs=sys_inputs)
        return {"success": True, "pdf_path": output_path}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
