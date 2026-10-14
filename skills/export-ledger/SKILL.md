---
name: export-ledger
description: Exports callback's application ledger to CSV. Use when the user asks to "export the ledger", "export my applications", "make the EDD report", "/export-ledger", or wants a spreadsheet of jobs and statuses, optionally filtered by status or date.
---

# Export Ledger

1. Turn the user's filter into arguments: a status ("applied", "rejected") becomes `status="Applied"`, matched against the start of each job's latest status; a date ("since October 1") becomes `since="YYYY-MM-DD"`.
2. If `.callback/config.json` sets `archive_dir`, use the absolute path of `<archive_dir>/ledger-export-<YYYY-MM-DD>.csv`; otherwise ask the user where to save it.
3. Call the callback MCP tool `export_ledger(output_path, status, since)`.
4. Report `data.path` and `data.rows`.
