---
name: witness
description: Review a pull request with Witness data-flow analysis. Use when asked to review a PR's data-flow changes, explain a changed hunk, or show the value paths behind a finding.
---

# Witness review

Witness shows how data moves through a pull request: which sources reach which sinks, which guards were added or bypassed, and which callers are new.

## Workflow

1. Start an analysis with the `analyze` MCP tool for the PR. It runs in the background and returns a job id.
2. Poll `overview` until `phase` is `done`. Present the overview first.
3. Page through `list_hunks` and show one hunk note at a time.
4. For a hunk the user asks about, call `hunk(id)` for its note and `paths(id, page)` for the exact value paths.

## Grounding rules

- Every claim must cite a finding id or a path line from the tool output. Do not state a flow that the output does not show.
- If a function or identifier is not in the output, say it is unknown instead of guessing.
- If coverage shows unanalysed files, say so in the answer.
- Keep each response short. Use paging instead of asking for the full graph.
- Explanations you write go through `submit_explanation` so the validator can check the citations.
