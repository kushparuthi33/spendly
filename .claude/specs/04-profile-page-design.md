# Spec: Profile Page Design

## Overview
Build a fully functional profile page where logged-in users can view their
account details (name, email, member-since date) and make two types of edits:
update their display name and change their password. This is Step 4 of the
Spendly roadmap and is the first authenticated-only page beyond the dashboard
placeholder, establishing the pattern for how protected pages are structured,
styled, and validated in this app.

## Depends on
- Step 01 — Database Setup (`users` table, `get_db()`, `get_user_by_id()` must exist)
- Step 02 — Registration (session setup, `create_user` in place)
- Step 03 — Login and Logout (session contains `user_id` and `user_name`)

## Routes
- `GET  /profile` — render the profile page with current user data — logged-in only
- `POST /profile` — handle name-update or password-change form submissions — logged-in only

## Database changes
No new tables or columns. Two new helper functions needed in `database/db.py`:

```python
def update_user_name(user_id, name):
    """Update the display name for the given user id."""

def update_user_password(user_id, password_hash):
    """Replace the stored password hash for the given user id."""
```

Both use parameterised queries. Both commit and close the connection.

## Templates
- **Create:** `templates/profile.html`
  - Extends `base.html`
  - Two visually separated card sections:
    1. **Account info** — displays name, email, and member-since date (read-only)
    2. **Edit name** — single-field form (`name`) that POSTs to `/profile` with a
       hidden `action=update_name` field
    3. **Change password** — three-field form (`current_password`, `new_password`,
       `confirm_password`) that POSTs to `/profile` with a hidden `action=change_password` field
  - Inline success/error flash message area per form section (use `success_name`,
    `error_name`, `success_password`, `error_password` template variables)
  - Use existing CSS classes where possible (`auth-section`, `auth-container`,
    `auth-header`, `btn-submit`, `auth-error`); add new classes only when needed
  - All colours via CSS variables — no hardcoded hex values

## Files to change
- `app.py`
  - Import `update_user_name`, `update_user_password` from `database.db`
  - Replace the `/profile` stub with a full `GET`/`POST` handler:
    - `GET` — call `get_user_by_id(session["user_id"])`, render `profile.html`
      with user data; redirect to `/login` if not authenticated
    - `POST action=update_name` — validate name (non-empty after strip, max 100
      chars), call `update_user_name`, refresh `session["user_name"]`, re-render
      with `success_name` or `error_name`
    - `POST action=change_password` — validate current password with
      `check_password_hash`, validate new password length ≥ 8, validate
      `new_password == confirm_password`, call `update_user_password` with
      `generate_password_hash(new_password)`, re-render with `success_password`
      or `error_password`
- `database/db.py`
  - Add `update_user_name(user_id, name)`
  - Add `update_user_password(user_id, password_hash)`

## Files to create
- `templates/profile.html`

## New dependencies
No new dependencies. Uses `werkzeug.security` functions already installed.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — never use string formatting in SQL
- Passwords verified with `werkzeug.security.check_password_hash`; new hashes
  generated with `werkzeug.security.generate_password_hash`
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Route guard: if `user_id` not in session, redirect to `url_for('login')`
- Dispatch on the hidden `action` field to keep a single `/profile` POST handler
- On name update success: update `session["user_name"]` so the navbar reflects
  the change immediately without a re-login
- On password change: do **not** clear the session — user stays logged in
- Re-populate the name field with the submitted value on validation failure
- Never reveal whether the current-password check passed or failed in separate
  error messages — use generic wording like "Current password is incorrect."
- Format `created_at` date as a human-readable string (e.g. "May 1, 2026")
  using Python's `datetime.strptime` / `.strftime`

## Definition of done
- [ ] Visiting `/profile` while logged out redirects to `/login`
- [ ] Visiting `/profile` while logged in renders the page with correct name,
      email, and member-since date pulled from the database
- [ ] Submitting the Edit Name form with a valid name updates the name in the
      database and immediately shows the new name in the navbar and on the page
- [ ] Submitting the Edit Name form with an empty name shows an inline error
      and does not update the database
- [ ] Submitting the Change Password form with the correct current password and
      matching new passwords (≥ 8 chars) updates the hash in the database
- [ ] After a successful password change the user remains logged in and can
      log out and back in with the new password
- [ ] Submitting Change Password with an incorrect current password shows
      "Current password is incorrect." without updating the database
- [ ] Submitting Change Password where new and confirm passwords don't match
      shows an error without updating the database
- [ ] Submitting Change Password with a new password shorter than 8 characters
      shows an error without updating the database
- [ ] No raw SQL with f-strings or `.format()` — all queries use `?` placeholders
- [ ] App starts without errors (`python3 app.py`)
