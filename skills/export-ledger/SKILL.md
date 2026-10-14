---
name: export-ledger
description: Exports callback's application ledger to CSV. Use when the user asks to "export the ledger", "export my applications", "make the EDD report", "/export-ledger", or wants a spreadsheet of jobs and statuses, optionally filtered by status or date.
---

# Export Ledger

1. Turn the user's filter into arguments. A date ("since October 1") becomes `since="YYYY-MM-DD"`. A status filter is a prefix match on the start of any of the job's status texts, so `status="Applied"` does not match `Already applied - confirmation recorded`. For an unemployment (EDD) report, pass `since` only, with no status, so applications and confirmations both appear; the user can filter the CSV afterward.
2. If `.callback/config.json` sets `archive_dir`, use the absolute path of `<archive_dir>/ledger_exports/ledger-export.csv`, overwriting the previous export. Use a dated name only if the user asks for one. Without `archive_dir`, ask the user where to save it.
3. Call the callback MCP tool `export_ledger(output_path, status, since)`.
4. Report `data.path` and `data.rows`. If it returns `invalid_output_path` (the path must be absolute and end in `.csv`) or `invalid_date` (`since` must be `YYYY-MM-DD`), tell the user and fix the argument. For `ledger_error`, report the message and stop.
