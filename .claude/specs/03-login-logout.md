# Spec: Login and Logout

## Overview
Implement user login and logout so registered users can authenticate into
Spendly and securely end their session. This step wires the existing
`POST /login` form to the database layer, validates credentials using
`werkzeug.security.check_password_hash`, stores the user identity in the
Flask session on success, and clears the session on logout. It also ensures
the dashboard is properly guarded — unauthenticated visitors are redirected
to `/login` (not `/register`). Step 02 (Registration) must be complete
before this step begins.

## Depends on
- Step 01 — Database Setup (`users` table, `get_db()`, `get_user_by_email()` must exist)
- Step 02 — Registration (session setup, `create_user`, `SECRET_KEY` all in place)

## Routes
- `GET  /login`  — render the login form — public (already exists as stub)
- `POST /login`  — process login form submission — public
- `GET  /logout` — clear session and redirect to `/login` — logged-in

## Database changes
No new tables or columns. One new query function needed in `database/db.py`:

```python
def get_user_by_id(user_id):
    """Return the user row for the given id, or None."""
```

All other lookups use `get_user_by_email` which already exists.

## Templates
- **Modify:** `templates/login.html`
  - Change `GET /login` route in `app.py` to accept both `GET` and `POST`
    (the template form already posts to `/login`).
  - Re-populate `email` field with `{{ email }}` on validation failure.
  - Template already has `{% if error %}<div class="auth-error">{{ error }}</div>{% endif %}` — keep it.

- **Modify:** `templates/dashboard.html`
  - Add a visible **Sign out** link/button that points to `url_for('logout')`.
  - Keep the existing welcome heading and subtitle.

## Files to change
- `app.py`
  - Import `check_password_hash` from `werkzeug.security`.
  - Import `get_user_by_id` from `database.db`.
  - Convert `GET /login` stub into a `GET`/`POST` handler:
    - `GET` — render `login.html`.
    - `POST` — validate email + password, set session, redirect to dashboard.
  - Implement `GET /logout`:
    - Call `session.clear()`.
    - Redirect to `url_for('login')`.
  - Fix the `GET /dashboard` guard: redirect to `url_for('login')` (not `register`) when `user_id` not in session.
- `database/db.py`
  - Add `get_user_by_id(user_id)` function.

## Files to create
No new files.

## New dependencies
No new pip packages. Uses `werkzeug.security.check_password_hash` (already installed).

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — never use string formatting in SQL
- Passwords verified with `werkzeug.security.check_password_hash` — never compare plaintext
- Use CSS variables — never hardcode hex values in any template or style
- All templates extend `base.html`
- Login validation order (server-side, before any session write):
  1. `email` — non-empty after strip
  2. `password` — non-empty
  3. User exists for that email (use `get_user_by_email`)
  4. Password matches stored hash (use `check_password_hash`)
- On any validation failure: re-render `login.html` with a generic error
  `"Invalid email or password."` — do **not** reveal which field is wrong
- On success: store `user_id` and `user_name` in `session`, then
  `redirect(url_for('dashboard'))`
- Logout must use `session.clear()` — do not delete individual keys
- After logout, redirect to `url_for('login')` — not the landing page

## Definition of done
- [ ] Visiting `/login` renders the login form
- [ ] Submitting valid credentials (e.g. demo@spendly.com / demo123) redirects
      to `/dashboard` showing the user's name
- [ ] Submitting an unknown email shows "Invalid email or password." (no crash)
- [ ] Submitting a correct email but wrong password shows "Invalid email or
      password." (no crash)
- [ ] Submitting with an empty email or empty password shows an error without
      writing to the database
- [ ] `email` field is re-populated on validation failure
- [ ] Visiting `/dashboard` without being logged in redirects to `/login`
      (not `/register`)
- [ ] Clicking Sign out clears the session and redirects to `/login`
- [ ] After logout, visiting `/dashboard` again redirects to `/login`
- [ ] App starts without errors (`python3 app.py`)
- [ ] No raw SQL strings with f-strings or `.format()` — all queries use `?`
      placeholders
