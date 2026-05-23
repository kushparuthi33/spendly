# Spec: Date Filter for Dashboard

## Overview
Add date-range filtering to the dashboard so users can narrow every stat, chart,
and transaction list to a chosen period. The filter is driven entirely by query-string
parameters (`from_date` / `to_date`) so it works without JavaScript and is
bookmarkable. Four preset shortcuts (This month, Last 3 months, Last 6 months,
All time) are rendered as links; a custom date-range form lets the user pick any
start and end date. When a filter is active all numbers on the page — totals,
category bars, and the expense table — reflect only the filtered window.

## Depends on
- Step 05 — Dashboard (template structure and stat cards)
- Step 06 — Backend routes for dashboard (db helper functions)

## Routes
- `GET /dashboard` — already exists; extend to read optional `from_date` and
  `to_date` query params (both `YYYY-MM-DD`). Access: logged-in.

No new routes are needed.

## Database changes
No new tables or columns. The following existing functions gain optional
`from_date` and `to_date` keyword arguments. When both are `None` the functions
behave exactly as before (no regression).

- `get_expenses_by_user(user_id, limit=30, from_date=None, to_date=None)`
- `get_category_totals(user_id, from_date=None, to_date=None)`
- `get_expense_count(user_id, from_date=None, to_date=None)`
- `get_total_spent(user_id, from_date=None, to_date=None)`

`get_monthly_total` is no longer called from the dashboard route when a custom
filter is active; remove it from the dashboard logic (keep the function itself
for potential future use).

## Templates
- **Modify:** `templates/dashboard.html`
  - Add a filter bar above the stat cards containing:
    - Four preset links: This month / Last 3 months / Last 6 months / All time
    - A collapsible (or always-visible) custom range form with two `<input type="date">` fields and a Submit button
    - An active-filter indicator that shows the current range when a filter is applied and a "Clear filter" link
  - Pass `from_date`, `to_date`, and `active_label` from the route so the
    template can highlight the active preset and show the range text

## Files to change
- `database/db.py` — extend four query functions with date-range params
- `app.py` — read `from_date` / `to_date` from `request.args`, validate them,
  compute preset ranges, pass filter context to the template
- `templates/dashboard.html` — add the filter bar UI

## Files to create
None.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — build the optional `WHERE date BETWEEN ? AND ?`
  clause by appending to a params list, never by string interpolation
- Passwords hashed with werkzeug (unchanged)
- Use CSS variables — never hardcode hex values in new styles
- All templates extend `base.html`
- Validate `from_date` / `to_date` in the route: if either cannot be parsed as
  `YYYY-MM-DD` with `datetime.strptime`, ignore both and fall back to "All time"
- `from_date` must not be after `to_date`; if it is, swap them silently
- Preset ranges are computed in the route using Python's `datetime` / `date`
  objects — no client-side JS date math
- The expense table still applies the 30-row `LIMIT` within the filtered window
- The "All time" preset passes `from_date=None, to_date=None` to the db helpers
  (no date clause added), matching current behaviour exactly

## Definition of done
- [ ] Visiting `/dashboard` with no query params behaves identically to before
      (all-time totals, last 30 expenses)
- [ ] Clicking "This month" filters all stats and the expense table to the
      current calendar month
- [ ] Clicking "Last 3 months" filters to the last 90 days relative to today
- [ ] Clicking "Last 6 months" filters to the last 180 days relative to today
- [ ] Clicking "All time" clears the filter and restores full totals
- [ ] Submitting the custom date form with a valid range filters the dashboard
      to that range
- [ ] Submitting an invalid date (non-date string) falls back to all-time
      without a 500 error
- [ ] When a filter is active, a label such as "Showing: 01 Jan 2026 – 31 May 2026"
      appears on the page with a "Clear" link that returns to all-time
- [ ] The active preset button or link is visually distinguished (e.g. different
      background or border) from the inactive ones
- [ ] Category totals and the "Top Category" stat card reflect only expenses
      within the filtered date range
- [ ] Expense count and total-spent stat cards reflect only the filtered range
- [ ] The page passes an HTML validator with no errors introduced by this feature
