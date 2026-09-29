---
name: frontend-source-first
description: Build or change PFT frontend UI by inspecting and reusing the existing pages, components, Tailwind tokens, and utilities before adding new source. Use for Next.js, React, and frontend styling work.
---

# Frontend Source First

Before adding UI source, inspect the relevant route, nearby shared components, `app/globals.css`, and the existing imports. Reuse an existing component or extend it when it already covers the need.

Use the project aliases and `cn` utility. Keep data fetching, request payloads, and user-visible financial meaning unchanged unless the task explicitly includes them. Prefer the configured shadcn component when it fits; inspect installed components before adding one.

Make narrow, composable changes. Preserve the current tokens, typography, and visual language unless a redesign is explicitly requested. Avoid duplicated page-local versions of shared controls, badges, and editors.

For visual changes, also use `responsive-ui-qa` before handoff.
