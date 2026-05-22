# Spec: Dashboard

## Overview
Replace the placeholder `/dashboard` route and template with a fully functional
expense dashboard. The page gives logged-in users an at-a-glance view of their
finances: a summary stats row (this month's total, expense count, and biggest
spending category), a per-category breakdown bar list, and a chronological table
of all their expenses. An "Add expense" button links forward to the future
`/expenses/add` route. No write operations are introduced in this step — it is
purely a read view powered by the existing `expenses` table.

## Depends on
- Step 01 — Database Setup (`expenses` table and `get_db()` must exist)
- Step 02 — Registration (session established)
- Step 03 — Login and Logout (`session["user_id"]` present for authenticated users)

## Routes
- `GET /dashboard` — render the full dashboard with live expense data — logged-in only

(Route already exists as a stub; it is upgraded, not added.)

## Database changes
No new tables or columns. Four new query functions needed in `database/db.py`:

```python
def get_expenses_by_user(user_id):
    """Return all expenses for user ordered by date DESC, then id DESC."""

def get_monthly_total(user_id, year, month):
    """Return (total_amount, count) for the given calendar month."""

def get_category_totals(user_id):
    """Return list of (category, total) ordered by total DESC."""

def get_expense_count(user_id):
    """Return total number of expenses for the user."""
```

All use parameterised queries. Each opens, queries, closes its own connection.

## Templates
- **Modify:** `templates/dashboard.html`
  - Replace the "coming soon" placeholder with the full dashboard layout
  - Top section: page heading ("Good [morning/afternoon/evening], {name}") and
    an "Add expense" `<a>` styled as `btn-primary` linking to `/expenses/add`
  - Stats row: three stat cards — This Month, Total Expenses (count), Top Category
  - Category breakdown section: a labelled bar list (category name, bar fill
    proportional to its share of total spending, amount label)
  - Expenses table: columns — Date, Description, Category, Amount — rows ordered
    date DESC; show "No expenses yet" empty state when list is empty
  - All colours via CSS variables — no hardcoded hex values
  - Extends `base.html`

- **Modify:** `templates/base.html`
  - Add a "Dashboard" nav link for logged-in users, appearing before "View profile"
  - Only show it when `request.path != '/dashboard'`

## Files to change
- `app.py`
  - Import the four new DB functions
  - Update `/dashboard` route:
    - Redirect to `/login` if `user_id` not in session (already done; keep it)
    - Call `get_expenses_by_user`, `get_monthly_total` (current month),
      `get_category_totals`, `get_expense_count`
    - Compute `greeting` ("Good morning" before 12:00, "Good afternoon" before
      18:00, "Good evening" otherwise) using `datetime.now().hour`
    - Pass all data to `dashboard.html`
- `database/db.py`
  - Add `get_expenses_by_user(user_id)`
  - Add `get_monthly_total(user_id, year, month)`
  - Add `get_category_totals(user_id)`
  - Add `get_expense_count(user_id)`
- `templates/dashboard.html` — full replacement (see Templates above)
- `templates/base.html` — add Dashboard nav link
- `static/css/style.css` — add dashboard layout classes (see rules below)

## Files to create
No new files.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — never use string formatting in SQL
- Passwords hashed with werkzeug (no password work in this step, rule still applies)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Route guard: if `user_id` not in session, redirect to `url_for('login')`
- Format expense dates (stored as `YYYY-MM-DD`) as `"May 1, 2026"` for display
- Format amounts as `₹{amount:,.2f}` (or plain `{amount:,.2f}` if rupee symbol
  causes encoding issues — be consistent across the page)
- Category bar widths: compute each bar's `width` as
  `(category_total / max_category_total * 100)%` — do this in the route and pass
  pre-computed percentages to the template, or compute in Jinja with `|float`
- The "Add expense" link goes to `url_for('add_expense')` — the route already
  exists as a stub; do not change it
- New CSS classes for dashboard layout must follow the existing naming convention
  (kebab-case, descriptive, no BEM)
- Do not use JavaScript for any data computation — all aggregation happens in Python

## Definition of done
- [ ] Visiting `/dashboard` while logged out redirects to `/login`
- [ ] Visiting `/dashboard` while logged in renders without errors
- [ ] "This Month" stat shows the correct sum of expenses dated in the current calendar month
- [ ] "Total Expenses" stat shows the correct count of all user expenses
- [ ] "Top Category" stat shows the category with the highest cumulative spend
- [ ] Category breakdown section lists every category that has at least one expense,
      with bars proportional to spend and the correct total shown
- [ ] Expenses table lists all expenses in date-descending order with correct
      date, description, category, and amount for each row
- [ ] Empty state ("No expenses yet") is shown when the user has zero expenses
- [ ] Greeting changes based on the time of day (morning / afternoon / evening)
- [ ] "Add expense" button links to `/expenses/add` without 404 (stub is fine)
- [ ] Dashboard nav link appears in the navbar for logged-in users on every page
      except `/dashboard` itself
- [ ] No raw SQL with f-strings or `.format()` — all queries use `?` placeholders
- [ ] App starts without errors (`python3 app.py`)
