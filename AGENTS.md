# PFT Agent Guide

Use the smallest relevant skill before making changes.

- `pft-safe-development` is required for any PFT work and governs financial data, Plaid, imports, classification, analytics, and Production boundaries.
- `frontend-source-first` applies to frontend work. Inspect and reuse the existing page, component, tokens, and utilities before adding code.
- `shadcn` applies when working with `components.json` or shadcn components. Use the project’s npm runner and inspect the existing component source before adding or updating a component.
- `responsive-ui-qa` applies to visual frontend changes. Mobile support is mandatory; complete rendered browser QA at narrow and desktop viewports before handoff.

Keep page redesigns, data behavior, and Production operations outside scope unless explicitly requested. Preserve existing styling while introducing UI primitives.

## Working directories

- The main checkout (`~/code/personal-finance-tracker`) stays on `main`. Agents do not edit files, switch branches, commit or stash there.
- Every agent works in its own git worktree, for example `git worktree add ../pft-<task> <branch>`. One worktree belongs to one agent and one branch.
- Never switch branches, commit or stash in another agent's worktree. The stash stack is shared across worktrees, so do not use bare `git stash` / `git stash pop`.
- Before starting, confirm the working directory and branch (`pwd`, `git worktree list`). If another agent is using the same directory, stop and ask the owner.
- Remove a finished worktree only after its branch is pushed or merged as the owner decides.

Delegate only self-contained, non-overlapping tasks. Give each subagent the relevant skills and file scope; the primary agent reviews diffs and runs final verification. Do not delegate Production writes, Plaid calls, or destructive financial-data operations.
