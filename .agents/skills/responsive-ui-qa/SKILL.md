---
name: responsive-ui-qa
description: Verify PFT frontend changes in a rendered browser at mobile and desktop widths. Use for any visual, layout, interaction, or component change.
---

# Responsive UI QA

Mobile support is required for every UI change. Test the affected route in a rendered browser at a narrow mobile viewport and a desktop viewport; include an intermediate width when layout changes near a breakpoint.

Check that content does not clip or cause unintended horizontal scrolling, controls remain reachable and tappable, text and financial values stay legible, forms and overlays work, and keyboard focus remains usable. Exercise the changed interaction and its loading, empty, and error states when available.

Use representative local or test data only. Do not call Production APIs, modify Production data, or trigger Plaid workflows for visual QA. Record the viewport coverage and any limitations in the handoff.
