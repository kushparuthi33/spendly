# Spec: Backend Routes for Dashboard Page

## Overview
Upgrade the three expense stub routes (`/expenses/add`, `/expenses/<id>/edit`,
`/expenses/<id>/delete`) into fully functional, form-backed views. This step
introduces all write operations for the `expenses` table — create, update, and
delete — so the dashboard becomes a live, user-maintained record rather than a
read-only view of seeded data. After this step every stat and row on the
dashboard reflects real input from the logged-in user.

## Depends on
- Step 01 — Database Setup (`expenses` table must exist)
- Step 02 — Registration (users must exist)
- Step 03 — Login and Logout (`session["user_id"]` present for auth checks)
- Step 05 — Dashboard (the page these routes feed into; redirect target after mutations)

## Routes
- `GET  /expenses/add` — render the add-expense form — logged-in only
- `POST /expenses/add` — validate and insert a new expense, redirect to `/dashboard` — logged-in only
- `GET  /expenses/<int:id>/edit` — render the edit-expense form pre-filled with existing data — logged-in only, must own the expense
- `POST /expenses/<int:id>/edit` — validate and update the expense, redirect to `/dashboard` — logged-in only, must own the expense
- `POST /expenses/<int:id>/delete` — delete the expense, redirect to `/dashboard` — logged-in only, must own the expense

## Database changes
No new tables or columns. Four new query functions needed in `database/db.py`:

```python
def add_expense(user_id, amount, category, date, description):
    """Insert a new expense row; return the new row's id."""

def get_expense_by_id(expense_id):
    """Return the expense row for the given id, or None."""

def update_expense(expense_id, amount, category, date, description):
    """Update amount, category, date, description for the given expense id."""

def delete_expense(expense_id):
    """Delete the expense row for the given id."""
```

All use parameterised queries. Each opens, queries, closes its own connection.

## Templates
- **Create:** `templates/expenses/add.html`
  - Extends `base.html`
  - Form with fields: Amount (number, step 0.01, min 0.01), Category (select),
    Date (date input, defaults to today), Description (text, optional)
  - Categories: Food, Transport, Bills, Health, Entertainment, Shopping, Other
  - Submit button labelled "Add Expense"; cancel link back to `/dashboard`
  - Inline error message block (re-renders form with values preserved on error)

- **Create:** `templates/expenses/edit.html`
  - Extends `base.html`
  - Same fields as add form, pre-filled with the expense's current values
  - Submit button labelled "Save Changes"; cancel link back to `/dashboard`
  - Inline error message block

## Files to change
- `app.py`
  - Import `add_expense`, `get_expense_by_id`, `update_expense`, `delete_expense` from `database.db`
  - Replace `add_expense` stub with GET+POST view:
    - GET: render `expenses/add.html`
    - POST: validate amount (positive float), category (must be in allowed list),
      date (non-empty, valid YYYY-MM-DD); on error re-render with error + values;
      on success call `add_expense(...)` and redirect to `url_for('dashboard')`
  - Replace `edit_expense` stub with GET+POST view:
    - Fetch expense with `get_expense_by_id(id)`; 404 if not found or
      `expense["user_id"] != session["user_id"]` (ownership check — return 403)
    - GET: render `expenses/edit.html` with expense data
    - POST: same validation as add; on success call `update_expense(...)` and
      redirect to `url_for('dashboard')`
  - Replace `delete_expense` stub with POST-only view:
    - Fetch expense; 404/403 on missing or wrong owner
    - Call `delete_expense(id)` and redirect to `url_for('dashboard')`
    - GET requests to this URL should redirect to `/dashboard` (no delete form needed)
- `database/db.py`
  - Add `add_expense(user_id, amount, category, date, description)`
  - Add `get_expense_by_id(expense_id)`
  - Add `update_expense(expense_id, amount, category, date, description)`
  - Add `delete_expense(expense_id)`

## Files to create
- `templates/expenses/add.html`
- `templates/expenses/edit.html`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — never use string formatting in SQL
- Passwords hashed with werkzeug (no password work in this step, rule still applies)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Route guard on every route: if `user_id` not in session, redirect to `url_for('login')`
- Ownership guard on edit and delete: if `expense["user_id"] != session["user_id"]`, abort(403)
- Allowed categories list must be defined once in `app.py` and passed to templates as `categories`
- Amount must be cast to `float` and validated > 0; reject non-numeric input with a form error
- Date must match the pattern `YYYY-MM-DD`; reject blank or malformed dates with a form error
- The delete route must only respond to POST — a GET to `/expenses/<id>/delete` redirects to `/dashboard`
- On successful add/edit/delete always redirect (POST-Redirect-GET pattern) to avoid re-submission
- Do not use JavaScript for form validation — all validation happens server-side in Python
- New CSS classes follow kebab-case naming convention matching existing `style.css`

## Definition of done
- [ ] Visiting `/expenses/add` while logged out redirects to `/login`
- [ ] GET `/expenses/add` renders the form with all seven category options
- [ ] Submitting the add form with valid data creates a new row and redirects to `/dashboard`
- [ ] The new expense appears immediately in the dashboard table and stats
- [ ] Submitting the add form with a blank or zero amount re-renders the form with an error and preserves other field values
- [ ] Submitting the add form with an invalid category re-renders with an error
- [ ] GET `/expenses/<id>/edit` pre-fills every field with the expense's current values
- [ ] Submitting the edit form with valid data updates the row and redirects to `/dashboard`
- [ ] Submitting the edit form with invalid data re-renders with an error and preserves field values
- [ ] Attempting to edit another user's expense returns 403
- [ ] POST `/expenses/<id>/delete` removes the row and redirects to `/dashboard`
- [ ] The deleted expense no longer appears in the dashboard table or stats
- [ ] Attempting to delete another user's expense returns 403
- [ ] GET `/expenses/<id>/delete` redirects to `/dashboard` (no accidental deletes via link)
- [ ] No raw SQL with f-strings or `.format()` — all queries use `?` placeholders
- [ ] App starts without errors (`python3 app.py`)
