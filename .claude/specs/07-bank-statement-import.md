# Spec: Bank Statement Import

## Overview
Allow logged-in users to upload a CSV or PDF bank statement and have their transactions
automatically extracted and categorised, then bulk-inserted into the `expenses`
table in a single confirmed batch. The core intelligence comes from the Claude
API (Anthropic): the raw CSV or PDF text is sent to the model, which returns structured
JSON containing date, description, amount, and a suggested category for each
transaction. A preview/confirmation step lets users correct any mis-categorised
rows and deselect transactions they don't want to import before anything is
written to the database. This eliminates the need to enter expenses one by one
and makes the dashboard immediately useful after onboarding.

## Depends on
- Step 01 — Database Setup (`expenses` table must exist)
- Step 03 — Login and Logout (session guard)
- Step 06 — Backend Routes for Dashboard Page (`EXPENSE_CATEGORIES` constant,
  `create_expense` db function available for reference)

## Routes
- `GET  /import` — render the CSV upload form — logged-in only
- `POST /import` — receive the uploaded file, send to Claude API, store parsed
  rows in session, redirect to preview — logged-in only
- `GET  /import/preview` — render the preview table from session data — logged-in only
- `POST /import/confirm` — validate session data, bulk-insert selected rows,
  clear session data, redirect to `/dashboard` — logged-in only

## Database changes
No new tables or columns. One new query function in `database/db.py`:

```python
def bulk_insert_expenses(rows):
    """
    rows: list of dicts with keys user_id, amount, category, date, description.
    Inserts all rows in a single transaction; rolls back entirely on any error.
    """
```

Uses `conn.executemany` with a single parameterised INSERT and a single commit.

## Templates
- **Create:** `templates/import/upload.html`
  - Extends `base.html`
  - Page heading: "Import Bank Statement"
  - Short instructions: accepted format (CSV), tip to export from their bank app
  - `<form enctype="multipart/form-data" method="POST">` with a file input
    (`accept=".csv"`) and a submit button "Parse Statement"
  - Error block: show `{{ error }}` if set
  - Link back to `/dashboard`

- **Create:** `templates/import/preview.html`
  - Extends `base.html`
  - Page heading: "Review Transactions" with a sub-heading showing the count
    ("X transactions found")
  - A `<form method="POST" action="/import/confirm">` wrapping a table with
    columns: Select (checkbox), Date, Description, Amount, Category (editable
    `<select>` populated from `{{ categories }}`), with each row's category
    pre-selected to Claude's suggestion
  - Each row has a hidden `<input name="row_index" value="{{ loop.index0 }}">` so
    the confirm route knows which rows were selected (only checked rows are
    submitted)
  - "Import Selected" submit button and a "Cancel" link back to `/dashboard`
  - Show a count of how many rows are pre-selected

- **Modify:** `templates/base.html`
  - No changes required (import is accessible via dashboard "Add expense" area)

## Files to change
- `app.py`
  - Import `bulk_insert_expenses` from `database.db` (add to module-level import)
  - Add `GET/POST /import` route
  - Add `GET /import/preview` route
  - Add `POST /import/confirm` route
- `database/db.py`
  - Add `bulk_insert_expenses(rows)` function
- `requirements.txt`
  - Add `anthropic` (latest stable)

## Files to create
- `templates/import/upload.html`
- `templates/import/preview.html`
- `utils/__init__.py` (empty, makes utils a package)
- `utils/statement_parser.py` — Claude API integration (see Rules below)

## New dependencies
- `anthropic` — Anthropic Python SDK for calling the Claude API

## Rules for implementation

### General
- No SQLAlchemy or ORMs
- Parameterised queries only — never f-strings or `.format()` in SQL
- Passwords hashed with werkzeug (no auth changes in this step)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Route guard on every route: if `user_id` not in session, redirect to `url_for('login')`

### File upload
- Use `request.files.get("file")` — if missing or filename is empty, re-render
  upload form with `error="Please select a CSV file."`
- Read file content with `file.read().decode("utf-8", errors="replace")` to
  handle encoding differences between banks
- Enforce a maximum file size of 1 MB; reject larger files with a clear error
- Only accept files whose name ends with `.csv`; reject others with a clear error

### Claude API integration (`utils/statement_parser.py`)
- Import `anthropic`; initialise `anthropic.Anthropic()` — the client reads
  `ANTHROPIC_API_KEY` from the environment automatically
- Use model `claude-haiku-4-5-20251001` (fast, cheap, sufficient for parsing)
- Enable **prompt caching** on the system message (add `"cache_control": {"type": "ephemeral"}` to the system content block) to reduce cost when multiple users upload files in the same session window
- System prompt must instruct Claude to:
  - Return **only** a JSON array, no prose, no markdown fences
  - Each element: `{"date": "YYYY-MM-DD", "description": "...", "amount": <float>, "category": "<one of the 7>"}`
  - Ignore non-transaction rows (headers, balance rows, summary rows)
  - Map categories to exactly: Food, Transport, Bills, Health, Entertainment, Shopping, Other
  - Use positive amounts only (ignore credits / reversals if ambiguous)
- Pass the raw CSV text as the user message
- Parse the response with `json.loads(response.content[0].text)`
- If parsing fails or the API raises an exception, raise a custom
  `ParseError(message)` exception that the route catches and shows as a
  user-friendly error
- Validate each returned row: `date` must match `YYYY-MM-DD`, `amount` must be
  a positive float, `category` must be in `EXPENSE_CATEGORIES`; skip invalid rows
  with a warning rather than aborting the whole import

### Session storage for preview
- After a successful parse, store the rows in `session["import_rows"]` as a
  list of dicts and redirect to `GET /import/preview`
- On `GET /import/preview`, if `session["import_rows"]` is missing or empty,
  redirect back to `GET /import` with an error flash
- On `POST /import/confirm`, read selected row indices from
  `request.form.getlist("row_index")`, look them up in `session["import_rows"]`,
  inject `session["user_id"]` as `user_id`, call `bulk_insert_expenses`, then
  `session.pop("import_rows", None)` and redirect to `url_for("dashboard")`

### Environment
- `ANTHROPIC_API_KEY` must be set in the environment; if missing at import time
  in `statement_parser.py`, raise an `EnvironmentError` with a helpful message
  that surfaces in the upload route as a user-facing error

## Definition of done
- [ ] Visiting `/import` while logged out redirects to `/login`
- [ ] GET `/import` renders the upload form without errors
- [ ] Uploading a non-CSV file re-renders the form with an error
- [ ] Uploading an empty or invalid CSV re-renders the form with an error
- [ ] Uploading a valid CSV with 5+ transactions calls the Claude API and
      redirects to `/import/preview`
- [ ] The preview table shows the correct number of rows with date, description,
      amount, and a pre-selected category for each
- [ ] Every row's category dropdown contains all 7 allowed categories
- [ ] Changing a category in the dropdown is reflected when the form is submitted
- [ ] Unchecking a row and confirming does NOT insert that row
- [ ] Confirming the import inserts only the selected rows into the `expenses` table
- [ ] After confirmation the user lands on `/dashboard` and the new expenses
      appear in the table and stats
- [ ] A missing `ANTHROPIC_API_KEY` shows a clear error on the upload page
      instead of crashing
- [ ] A Claude API error (network failure, quota exceeded) shows a user-friendly
      error on the upload page
- [ ] `bulk_insert_expenses` rolls back entirely if any single insert fails
- [ ] No raw SQL with f-strings — all queries use `?` placeholders
- [ ] App starts without errors (`python3 app.py`)
