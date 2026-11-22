"""CSV text for ledger exports."""

import csv
import io

from callback.repositories import ledger


def csv_text(rows: list[dict], columns: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    writer.writerows(ledger.spreadsheet_safe(row) for row in rows)
    return buffer.getvalue()
