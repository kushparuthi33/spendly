# Spec: Registration

## Overview
Implement user registration so new visitors can create a Spendly account.
This step wires the existing `POST /register` form to the database layer,
validates inputs, hashes the password, inserts the new user, starts a Flask
session, and redirects to the dashboard. It also adds `SECRET_KEY` to the
app so Flask sessions work. Step 1 (database setup) must be complete before
this step begins.

## Depends on
- Step 01 — Database Setup (`users` table and `get_db()` must exist)

## Routes
- `GET  /register` — render the registration form — public (already exists, no change)
- `POST /register` — process registration form submission — public

## Database changes
No new tables or columns. One new query function needed in `database/db.py`:

```python
def create_user(name, email, password_hash):
    """Insert a new user row. Returns the new user's id."""

def get_user_by_email(email):
    """Return the user row for the given email, or None."""
```

Always verify against `database/db.py` — `users` table already exists with
columns: `id`, `name`, `email`, `password_hash`, `created_at`.

## Templates
- **Modify:** `templates/register.html`
  - Re-populate `name` and `email` fields with `{{ request.form.name }}` /
    `{{ request.form.email }}` on validation failure so the user doesn't
    re-type everything.
  - Template already has `{% if error %}<div class="auth-error">{{ error }}</div>{% endif %}` — keep it.

- **Create:** `templates/dashboard.html`
  - Minimal page extending `base.html` that shows "Welcome, {{ name }}!" and
    a placeholder message ("Expense list coming soon").
  - This is the redirect target after a successful registration.

## Files to change
- `app.py`
  - Add `SECRET_KEY` to the app config (use `os.urandom(24)` or a fixed dev
    string — store in env var `SECRET_KEY` with a fallback).
  - Import `session`, `redirect`, `url_for`, `request`, `flash` from flask.
  - Import `create_user`, `get_user_by_email` from `database.db`.
  - Convert `GET /register` route to accept `GET` and add `POST /register`
    handler (or use `methods=["GET", "POST"]` on one function).
- `database/db.py`
  - Add `create_user(name, email, password_hash)` function.
  - Add `get_user_by_email(email)` function.

## Files to create
- `templates/dashboard.html` — minimal logged-in landing page

## New dependencies
No new pip packages. Uses `flask.session` (built-in), `os` (stdlib), and
`werkzeug.security.generate_password_hash` (already installed).

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — never use string formatting in SQL
- Passwords hashed with `werkzeug.security.generate_password_hash` before
  any DB write — never store plaintext
- Use CSS variables — never hardcode hex values in any template or style
- All templates extend `base.html`
- Validate on the server side before touching the database:
  1. `name` — non-empty after strip
  2. `email` — non-empty after strip
  3. `password` — minimum 8 characters
  4. Email not already registered (use `get_user_by_email`)
- On any validation failure: re-render `register.html` with a descriptive
  `error` string — do **not** redirect
- On success: call `create_user`, store `user_id` and `user_name` in
  `session`, then `redirect(url_for('dashboard'))`
- `SECRET_KEY` must be set on the Flask app before any session usage

## Definition of done
- [ ] Submitting the form with a new name/email/password creates a row in
      the `users` table with a hashed password (not plaintext)
- [ ] After successful registration the browser lands on `/dashboard` showing
      the user's name
- [ ] Submitting with a duplicate email re-renders the register page with an
      error message (no crash, no redirect)
- [ ] Submitting with a password shorter than 8 characters shows a validation
      error without writing to the database
- [ ] Submitting with an empty name shows a validation error
- [ ] `name` and `email` fields are re-populated on validation failure
- [ ] App starts without errors (`python3 app.py`)
- [ ] No raw SQL strings with f-strings or `.format()` — all queries use `?`
      placeholders
