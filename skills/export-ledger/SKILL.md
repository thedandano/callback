---
name: export-ledger
description: Exports callback's application ledger to CSV. Use when the user asks to "export the ledger", "export my applications", "make the EDD report", "/export-ledger", or wants a spreadsheet of jobs and statuses, optionally filtered by status or date.
---

# Export Ledger

1. Turn the user's filter into arguments. A date ("since October 1") becomes `since="YYYY-MM-DD"`. A status filter is a prefix match on the start of the status text, so `status="Applied"` does not match `Already applied - confirmation recorded`. Pick the mode: `mode="jobs"` (default) gives one row per job with its latest status and scores; `mode="events"` gives one row per status event with its own date; `mode="contacts"` is the events view kept to reportable contacts only (statuses starting `Applied` or `Already applied`, and notes starting `Contact method:`), so skipped, staged and rejection events are left out. For an unemployment (EDD) report, use `mode="contacts"` with `since` and no status, so every application and confirmation appears with its own date. The export's `Notes` column starts with `Contact method: Online`, `Email`, `Phone`, `Mail`, `Fax`, or `In person` for application/contact records; that prefix is the contact-method field.
2. If `.callback/config.json` sets `archive_dir`, use the absolute path of `<archive_dir>/ledger_exports/ledger-export.csv`, overwriting the previous export. Use a dated name only if the user asks for one. Without `archive_dir`, ask the user where to save it.
3. Call the callback MCP tool `export_ledger(output_path, status, since, mode)`.
4. Report `data.path` and `data.rows`. If it returns `invalid_output_path` (the path must be absolute and end in `.csv`), `invalid_date` (`since` must be `YYYY-MM-DD`), or `invalid_mode` (`jobs`, `events`, or `contacts`; keep `contacts` for an EDD report), tell the user and fix the argument. For `ledger_error`, report the message and stop.
