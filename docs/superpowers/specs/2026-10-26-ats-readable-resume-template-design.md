# ATS-readable resume template (GitHub #145)

## Goal

Make the rendered resume closer to Jeff Su Rule 1’s boring, standard section layout so ATS parsers see clear headings in a conventional order.

## Scope (this pass)

- Rename printed section headers to plain names: `EXPERIENCE`, `PROJECTS`, `EDUCATION`, `SKILLS` (keep existing all-caps template style).
- Reorder template blocks to: **Summary → Experience → Projects → Education → Skills**.
- Update render tests that assert the old skills header / section order.

## Out of scope

- Experience date sorting at render time (deferred).
- PDF file-size warning (deferred).
- Scorer / SectionMap / tailor / extractor changes.

## Approach

Edit `callback/render/resume_template.html.j2` only for product behavior. Tailoring already maps by semantic keys; display headings are hardcoded in the template.
