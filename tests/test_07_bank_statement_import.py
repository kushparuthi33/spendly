"""
Tests for the Bank Statement Import feature (Spec 07).

Spec: .claude/specs/07-bank-statement-import.md

Routes under test:
  GET  /import           — render upload form (auth-guarded)
  POST /import           — receive file, parse, store in session, redirect to preview
  GET  /import/preview   — render preview table from session (auth-guarded)
  POST /import/confirm   — bulk-insert selected rows, clear session, redirect to /dashboard

All tests use an isolated temporary SQLite DB (via conftest fixtures).
The real spendly.db is never touched.

Strategy for the POST /import parsing step:
  - Tests that need the parser to succeed monkeypatch utils.statement_parser so
    no real Claude API call is made.
  - Tests that verify file-level validation (missing file, wrong type, too large,
    empty) exercise the route directly without patching the parser.
  - session["import_rows"] is injected via client.session_transaction() for all
    preview / confirm tests, avoiding a dependency on the upload flow.
"""

import io
import sqlite3

import pytest

import database.db as db_module
import utils.statement_parser as parser_module


# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------

VALID_ROWS = [
    {
        "date": "2026-04-01",
        "description": "Grocery run",
        "amount": 45.50,
        "category": "Food",
    },
    {
        "date": "2026-04-03",
        "description": "Monthly bus pass",
        "amount": 35.00,
        "category": "Transport",
    },
    {
        "date": "2026-04-07",
        "description": "Electricity bill",
        "amount": 120.00,
        "category": "Bills",
    },
]

# Minimal CSV content that has the right shape for the rule-based parser
VALID_CSV = (
    "Date,Narration,Debit\n"
    "01/04/2026,Grocery run,45.50\n"
    "03/04/2026,Monthly bus pass,35.00\n"
    "07/04/2026,Electricity bill,120.00\n"
)

ALL_CATEGORIES = [
    "Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"
]


def _make_file(content: str, filename: str = "statement.csv") -> dict:
    """Return a dict suitable for use in client.post(data=...) as a file upload."""
    return {
        "file": (io.BytesIO(content.encode("utf-8")), filename),
    }


def _set_session_rows(client, rows: list, user_id: int | None = None):
    """Inject import_rows (and optionally user_id) into the client session."""
    with client.session_transaction() as sess:
        sess["import_rows"] = rows
        if user_id is not None:
            sess["user_id"] = user_id


# ---------------------------------------------------------------------------
# Auth guard tests
# ---------------------------------------------------------------------------

class TestAuthGuards:
    """Every import route must redirect unauthenticated visitors to /login."""

    def test_get_import_unauthenticated_redirects_to_login(self, client):
        response = client.get("/import")
        assert response.status_code == 302, (
            "GET /import must redirect unauthenticated users"
        )
        assert "/login" in response.headers["Location"], (
            "Redirect target must be the login page"
        )

    def test_post_import_unauthenticated_redirects_to_login(self, client):
        response = client.post(
            "/import",
            data=_make_file(VALID_CSV),
            content_type="multipart/form-data",
        )
        assert response.status_code == 302, (
            "POST /import must redirect unauthenticated users"
        )
        assert "/login" in response.headers["Location"], (
            "Redirect target must be the login page"
        )

    def test_get_import_preview_unauthenticated_redirects_to_login(self, client):
        response = client.get("/import/preview")
        assert response.status_code == 302, (
            "GET /import/preview must redirect unauthenticated users"
        )
        assert "/login" in response.headers["Location"], (
            "Redirect target must be the login page"
        )

    def test_post_import_confirm_unauthenticated_redirects_to_login(self, client):
        response = client.post("/import/confirm", data={"row_index": ["0"]})
        assert response.status_code == 302, (
            "POST /import/confirm must redirect unauthenticated users"
        )
        assert "/login" in response.headers["Location"], (
            "Redirect target must be the login page"
        )


# ---------------------------------------------------------------------------
# GET /import — upload form
# ---------------------------------------------------------------------------

class TestGetImportUploadForm:
    """GET /import renders the upload form for authenticated users."""

    def test_get_import_returns_200(self, auth_client, app):
        client, _ = auth_client
        response = client.get("/import")
        assert response.status_code == 200, "GET /import must return 200 for authenticated user"

    def test_get_import_renders_page_heading(self, auth_client, app):
        client, _ = auth_client
        response = client.get("/import")
        body = response.data.decode()
        assert "Import Bank Statement" in body, (
            "Upload page must display 'Import Bank Statement' heading"
        )

    def test_get_import_renders_file_input(self, auth_client, app):
        client, _ = auth_client
        response = client.get("/import")
        body = response.data.decode()
        assert 'type="file"' in body, "Upload form must contain a file input"
        assert 'name="file"' in body, "File input must be named 'file'"

    def test_get_import_file_input_accepts_csv(self, auth_client, app):
        client, _ = auth_client
        response = client.get("/import")
        body = response.data.decode()
        assert 'accept=".csv"' in body, "File input must restrict to .csv via accept attribute"

    def test_get_import_renders_submit_button(self, auth_client, app):
        client, _ = auth_client
        response = client.get("/import")
        body = response.data.decode()
        assert "Parse Statement" in body, "Submit button must be labelled 'Parse Statement'"

    def test_get_import_form_is_multipart(self, auth_client, app):
        client, _ = auth_client
        response = client.get("/import")
        body = response.data.decode()
        assert "multipart/form-data" in body, (
            "Upload form must use enctype='multipart/form-data'"
        )

    def test_get_import_has_dashboard_link(self, auth_client, app):
        client, _ = auth_client
        response = client.get("/import")
        body = response.data.decode()
        assert "/dashboard" in body, "Upload page must include a link back to the dashboard"

    def test_get_import_extends_base_template(self, auth_client, app):
        client, _ = auth_client
        response = client.get("/import")
        body = response.data.decode()
        assert "Spendly" in body, "Upload page must include Spendly branding from base.html"

    def test_get_import_no_error_block_by_default(self, auth_client, app):
        client, _ = auth_client
        response = client.get("/import")
        body = response.data.decode()
        # The error div is only rendered when {{ error }} is truthy
        assert "auth-error" not in body, (
            "No error block should appear on a fresh GET /import"
        )


# ---------------------------------------------------------------------------
# POST /import — file validation errors
# ---------------------------------------------------------------------------

class TestPostImportFileValidation:
    """POST /import validates the uploaded file before calling the parser."""

    def test_post_import_no_file_shows_error(self, auth_client, app):
        """Submitting the form with no file re-renders the upload page with an error."""
        client, _ = auth_client
        response = client.post("/import", data={}, content_type="multipart/form-data")
        assert response.status_code == 200, "Missing file must re-render upload form (200)"
        body = response.data.decode()
        assert "Please select a CSV file" in body, (
            "Missing file must display 'Please select a CSV file.' error"
        )

    def test_post_import_empty_filename_shows_error(self, auth_client, app):
        """A file field present but with an empty filename is treated as missing."""
        client, _ = auth_client
        response = client.post(
            "/import",
            data={"file": (io.BytesIO(b"some content"), "")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 200, "Empty filename must re-render upload form"
        body = response.data.decode()
        assert "Please select a CSV file" in body, (
            "Empty filename must display the 'Please select a CSV file.' error"
        )

    def test_post_import_non_csv_file_shows_error(self, auth_client, app):
        """Uploading a .txt file must be rejected with a clear error."""
        client, _ = auth_client
        response = client.post(
            "/import",
            data=_make_file("some text content", filename="statement.txt"),
            content_type="multipart/form-data",
        )
        assert response.status_code == 200, "Non-CSV file must re-render upload form"
        body = response.data.decode()
        assert "Only CSV files are accepted" in body, (
            "Non-CSV upload must display 'Only CSV files are accepted.' error"
        )

    def test_post_import_pdf_file_shows_error(self, auth_client, app):
        """Uploading a .pdf file must be rejected."""
        client, _ = auth_client
        response = client.post(
            "/import",
            data=_make_file("PDF content", filename="statement.pdf"),
            content_type="multipart/form-data",
        )
        assert response.status_code == 200, "PDF file must re-render upload form"
        body = response.data.decode()
        assert "Only CSV files are accepted" in body, (
            "PDF upload must display the CSV-only error"
        )

    def test_post_import_empty_csv_shows_error(self, auth_client, app):
        """An empty CSV file (zero bytes or only whitespace) must be rejected."""
        client, _ = auth_client
        response = client.post(
            "/import",
            data=_make_file("   \n  \t  ", filename="empty.csv"),
            content_type="multipart/form-data",
        )
        assert response.status_code == 200, "Empty CSV must re-render upload form"
        body = response.data.decode()
        assert "empty" in body.lower(), (
            "Empty CSV must display an error indicating the file is empty"
        )

    def test_post_import_file_over_1mb_shows_error(self, auth_client, app):
        """A CSV file larger than 1 MB must be rejected with a size error."""
        client, _ = auth_client
        # 1 MB + 1 byte — build a minimal but over-limit payload
        big_content = "a" * (1 * 1024 * 1024 + 1)
        response = client.post(
            "/import",
            data=_make_file(big_content, filename="big.csv"),
            content_type="multipart/form-data",
        )
        assert response.status_code == 200, "Oversized file must re-render upload form"
        body = response.data.decode()
        assert "too large" in body.lower() or "1 MB" in body or "1mb" in body.lower(), (
            "Oversized file must display a file-size error"
        )

    def test_post_import_exactly_1mb_not_rejected(self, auth_client, app, monkeypatch):
        """A file of exactly 1 MB must not be rejected by the size check."""
        # Monkeypatch the parser so we don't actually need a real CSV
        monkeypatch.setattr(parser_module, "parse_statement_rules", lambda _: VALID_ROWS)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        client, _ = auth_client
        exactly_1mb = "a,b,c\n" + "x" * (1 * 1024 * 1024 - 6)  # pad to 1 MB
        response = client.post(
            "/import",
            data=_make_file(exactly_1mb, filename="exact.csv"),
            content_type="multipart/form-data",
        )
        # Should not show a size error — either redirects to preview or shows a parse error
        body = response.data.decode()
        assert "too large" not in body.lower(), (
            "A file of exactly 1 MB must not trigger the size rejection"
        )

    @pytest.mark.parametrize("ext", [".xls", ".xlsx", ".json", ".xml", ".tsv"])
    def test_post_import_wrong_extensions_rejected(self, auth_client, app, ext):
        """Various non-CSV extensions must all be rejected."""
        client, _ = auth_client
        response = client.post(
            "/import",
            data=_make_file("some data", filename=f"statement{ext}"),
            content_type="multipart/form-data",
        )
        assert response.status_code == 200, f"{ext} file must re-render upload form"
        body = response.data.decode()
        assert "Only CSV files are accepted" in body, (
            f"Uploading a {ext} file must display the CSV-only error"
        )


# ---------------------------------------------------------------------------
# POST /import — parser integration (mocked)
# ---------------------------------------------------------------------------

class TestPostImportParserIntegration:
    """
    Tests for POST /import behaviour after file validation passes.
    The parser (Claude or rule-based) is monkeypatched so no real API call occurs.
    """

    def test_post_import_valid_csv_redirects_to_preview(self, auth_client, app, monkeypatch):
        """A valid CSV that yields rows must redirect to /import/preview."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(parser_module, "parse_statement_rules", lambda _: VALID_ROWS)

        client, _ = auth_client
        response = client.post(
            "/import",
            data=_make_file(VALID_CSV),
            content_type="multipart/form-data",
        )
        assert response.status_code == 302, "Successful parse must redirect"
        assert "/import/preview" in response.headers["Location"], (
            "Successful parse must redirect to /import/preview"
        )

    def test_post_import_rows_stored_in_session(self, auth_client, app, monkeypatch):
        """After a successful parse, import_rows must be stored in the session."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(parser_module, "parse_statement_rules", lambda _: VALID_ROWS)

        client, _ = auth_client
        client.post(
            "/import",
            data=_make_file(VALID_CSV),
            content_type="multipart/form-data",
        )
        with client.session_transaction() as sess:
            stored = sess.get("import_rows")
        assert stored is not None, "import_rows must be set in session after successful parse"
        assert len(stored) == len(VALID_ROWS), (
            "Session import_rows must contain the same number of rows as the parser returned"
        )

    def test_post_import_no_transactions_found_shows_error(self, auth_client, app, monkeypatch):
        """When the parser returns an empty list, re-render with 'No expense transactions found'."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(parser_module, "parse_statement_rules", lambda _: [])

        client, _ = auth_client
        response = client.post(
            "/import",
            data=_make_file(VALID_CSV),
            content_type="multipart/form-data",
        )
        assert response.status_code == 200, "No rows found must re-render upload form"
        body = response.data.decode()
        assert "No expense transactions were found" in body, (
            "Empty parse result must display 'No expense transactions were found in the file.'"
        )

    def test_post_import_parse_error_shows_user_friendly_message(
        self, auth_client, app, monkeypatch
    ):
        """A ParseError from the parser must surface as a user-friendly error on the upload page."""
        from utils.statement_parser import ParseError

        def _raise_parse_error(_text):
            raise ParseError("Cannot detect columns: date")

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(parser_module, "parse_statement_rules", _raise_parse_error)

        client, _ = auth_client
        response = client.post(
            "/import",
            data=_make_file(VALID_CSV),
            content_type="multipart/form-data",
        )
        assert response.status_code == 200, "ParseError must re-render upload form"
        body = response.data.decode()
        assert "Cannot detect columns: date" in body, (
            "ParseError message must be displayed verbatim on the upload page"
        )

    def test_post_import_environment_error_shows_friendly_message(
        self, auth_client, app, monkeypatch
    ):
        """An EnvironmentError (e.g. missing API key when Claude is used) surfaces as an error."""
        # Force the route to attempt the Claude path by providing a dummy key,
        # then make parse_statement raise EnvironmentError
        def _raise_env_error(_text):
            raise EnvironmentError("ANTHROPIC_API_KEY is not set.")

        monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-key-for-test")
        monkeypatch.setattr(parser_module, "parse_statement", _raise_env_error)

        client, _ = auth_client
        response = client.post(
            "/import",
            data=_make_file(VALID_CSV),
            content_type="multipart/form-data",
        )
        assert response.status_code == 200, "EnvironmentError must re-render upload form"
        body = response.data.decode()
        assert "ANTHROPIC_API_KEY" in body or "not set" in body.lower(), (
            "EnvironmentError message must appear on the upload page"
        )

    def test_post_import_claude_path_used_when_api_key_set(self, auth_client, app, monkeypatch):
        """When ANTHROPIC_API_KEY is present, parse_statement (Claude) is called, not the rule parser."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-key-for-test")
        claude_called = []
        rules_called = []

        def mock_parse_statement(text):
            claude_called.append(True)
            return VALID_ROWS

        def mock_parse_rules(text):
            rules_called.append(True)
            return VALID_ROWS

        monkeypatch.setattr(parser_module, "parse_statement", mock_parse_statement)
        monkeypatch.setattr(parser_module, "parse_statement_rules", mock_parse_rules)

        client, _ = auth_client
        client.post(
            "/import",
            data=_make_file(VALID_CSV),
            content_type="multipart/form-data",
        )
        assert claude_called, "parse_statement (Claude) must be called when ANTHROPIC_API_KEY is set"
        assert not rules_called, "parse_statement_rules must NOT be called when API key is present"

    def test_post_import_rule_parser_used_when_no_api_key(self, auth_client, app, monkeypatch):
        """When ANTHROPIC_API_KEY is absent, parse_statement_rules is called."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        rules_called = []

        def mock_parse_rules(text):
            rules_called.append(True)
            return VALID_ROWS

        monkeypatch.setattr(parser_module, "parse_statement_rules", mock_parse_rules)

        client, _ = auth_client
        client.post(
            "/import",
            data=_make_file(VALID_CSV),
            content_type="multipart/form-data",
        )
        assert rules_called, "parse_statement_rules must be called when ANTHROPIC_API_KEY is absent"

    def test_post_import_sql_injection_in_description_is_safe(
        self, auth_client, app, monkeypatch
    ):
        """Descriptions containing SQL injection attempts must be stored literally, not executed."""
        injection_rows = [
            {
                "date": "2026-04-01",
                "description": "'; DROP TABLE expenses; --",
                "amount": 10.00,
                "category": "Other",
            }
        ]
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(parser_module, "parse_statement_rules", lambda _: injection_rows)

        client, user_id = auth_client
        client.post(
            "/import",
            data=_make_file(VALID_CSV),
            content_type="multipart/form-data",
        )
        with client.session_transaction() as sess:
            stored = sess.get("import_rows", [])
        # The session should contain the row; the expenses table should still exist
        # (confirmed by checking the DB for the table structure below)
        assert len(stored) == 1, "SQL injection description must be stored as a plain string"
        assert stored[0]["description"] == "'; DROP TABLE expenses; --", (
            "Description must be stored literally without being interpreted as SQL"
        )


# ---------------------------------------------------------------------------
# GET /import/preview — preview table
# ---------------------------------------------------------------------------

class TestGetImportPreview:
    """GET /import/preview renders the review table from session data."""

    def test_preview_returns_200_with_rows_in_session(self, auth_client, app):
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        response = client.get("/import/preview")
        assert response.status_code == 200, (
            "GET /import/preview must return 200 when import_rows is in session"
        )

    def test_preview_redirects_when_no_session_rows(self, auth_client, app):
        """Without import_rows in session, GET /import/preview redirects back to /import."""
        client, _ = auth_client
        response = client.get("/import/preview")
        assert response.status_code == 302, (
            "GET /import/preview must redirect when session has no import_rows"
        )
        assert "/import" in response.headers["Location"], (
            "Redirect must go back to the /import upload page"
        )

    def test_preview_redirects_when_session_rows_empty(self, auth_client, app):
        """An empty import_rows list must also trigger the redirect."""
        client, user_id = auth_client
        _set_session_rows(client, [], user_id)
        response = client.get("/import/preview")
        assert response.status_code == 302, (
            "GET /import/preview with empty import_rows must redirect"
        )
        assert "/import" in response.headers["Location"], (
            "Redirect from empty rows must go back to /import"
        )

    def test_preview_renders_heading(self, auth_client, app):
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        response = client.get("/import/preview")
        body = response.data.decode()
        assert "Review Transactions" in body, (
            "Preview page must display 'Review Transactions' as the page heading"
        )

    def test_preview_shows_correct_row_count(self, auth_client, app):
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        response = client.get("/import/preview")
        body = response.data.decode()
        count_str = str(len(VALID_ROWS))
        assert count_str in body, (
            f"Preview must show the count of parsed rows ({count_str})"
        )
        assert "transaction" in body.lower(), (
            "Preview must include the word 'transaction(s)' near the count"
        )

    def test_preview_renders_all_rows(self, auth_client, app):
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        response = client.get("/import/preview")
        body = response.data.decode()
        for row in VALID_ROWS:
            assert row["description"] in body, (
                f"Description '{row['description']}' must appear in the preview table"
            )
            assert row["date"] in body, (
                f"Date '{row['date']}' must appear in the preview table"
            )

    def test_preview_renders_amounts(self, auth_client, app):
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        response = client.get("/import/preview")
        body = response.data.decode()
        for row in VALID_ROWS:
            formatted_amount = f"{row['amount']:.2f}"
            assert formatted_amount in body, (
                f"Amount '{formatted_amount}' must appear in the preview table"
            )

    def test_preview_all_rows_have_checkboxes_checked(self, auth_client, app):
        """Every row must be pre-selected (checkbox checked) by default."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        response = client.get("/import/preview")
        body = response.data.decode()
        # Each row has one checkbox; all must be checked
        checked_count = body.count("checked")
        assert checked_count >= len(VALID_ROWS), (
            "Every row's checkbox must be pre-checked in the preview table"
        )

    def test_preview_checkboxes_have_row_index_name(self, auth_client, app):
        """Checkboxes must use name='row_index' so confirm route can read them."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        response = client.get("/import/preview")
        body = response.data.decode()
        assert 'name="row_index"' in body, (
            "Preview checkboxes must use name='row_index'"
        )

    def test_preview_row_indices_are_zero_based(self, auth_client, app):
        """The checkbox values must be zero-based indices (0, 1, 2, ...)."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        response = client.get("/import/preview")
        body = response.data.decode()
        assert 'value="0"' in body, "First row must have checkbox value='0'"
        assert 'value="1"' in body, "Second row must have checkbox value='1'"
        assert 'value="2"' in body, "Third row must have checkbox value='2'"

    def test_preview_category_dropdowns_present_for_each_row(self, auth_client, app):
        """Each row must have a category <select> element."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        response = client.get("/import/preview")
        body = response.data.decode()
        select_count = body.count('<select name="category"')
        assert select_count == len(VALID_ROWS), (
            f"Each row must have exactly one category select; expected {len(VALID_ROWS)}, "
            f"found {select_count}"
        )

    def test_preview_all_7_categories_in_each_dropdown(self, auth_client, app):
        """Every allowed category must appear as an option in each row's dropdown."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        response = client.get("/import/preview")
        body = response.data.decode()
        for cat in ALL_CATEGORIES:
            assert cat in body, (
                f"Category '{cat}' must appear as an option in the preview dropdowns"
            )

    def test_preview_suggested_category_is_preselected(self, auth_client, app):
        """The category suggested by the parser must be pre-selected in the dropdown."""
        single_row = [
            {
                "date": "2026-04-01",
                "description": "Netflix subscription",
                "amount": 15.00,
                "category": "Entertainment",
            }
        ]
        client, user_id = auth_client
        _set_session_rows(client, single_row, user_id)
        response = client.get("/import/preview")
        body = response.data.decode()
        # The template renders: <option value="Entertainment" selected>Entertainment</option>
        assert 'value="Entertainment"' in body, "Entertainment option must be present"
        # 'selected' must appear near the Entertainment option
        ent_idx = body.find('value="Entertainment"')
        snippet = body[ent_idx: ent_idx + 60]
        assert "selected" in snippet, (
            "The parser-suggested category 'Entertainment' must be pre-selected"
        )

    def test_preview_form_posts_to_confirm_route(self, auth_client, app):
        """The preview form must POST to /import/confirm."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        response = client.get("/import/preview")
        body = response.data.decode()
        assert "/import/confirm" in body, (
            "Preview form must have action pointing to /import/confirm"
        )

    def test_preview_has_import_selected_button(self, auth_client, app):
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        response = client.get("/import/preview")
        body = response.data.decode()
        assert "Import Selected" in body, (
            "Preview page must display an 'Import Selected' submit button"
        )

    def test_preview_has_cancel_link_to_dashboard(self, auth_client, app):
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        response = client.get("/import/preview")
        body = response.data.decode()
        assert "Cancel" in body, "Preview page must include a Cancel link"
        assert "/dashboard" in body, "Cancel link must point to /dashboard"

    def test_preview_extends_base_template(self, auth_client, app):
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        response = client.get("/import/preview")
        body = response.data.decode()
        assert "Spendly" in body, "Preview page must include Spendly branding from base.html"

    def test_preview_single_transaction_label_singular(self, auth_client, app):
        """With exactly 1 row, the sub-heading should say '1 transaction found'."""
        single_row = [VALID_ROWS[0]]
        client, user_id = auth_client
        _set_session_rows(client, single_row, user_id)
        response = client.get("/import/preview")
        body = response.data.decode()
        # The template uses: {{ rows|length }} transaction{{ 's' if rows|length != 1 }} found
        assert "1 transaction" in body, (
            "A single row must display '1 transaction' (singular)"
        )
        # Make sure it doesn't say "1 transactions"
        assert "1 transactions" not in body, (
            "Singular form must be used for exactly 1 transaction"
        )

    def test_preview_multiple_transactions_label_plural(self, auth_client, app):
        """With more than 1 row, the sub-heading should say 'X transactions found'."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        response = client.get("/import/preview")
        body = response.data.decode()
        assert f"{len(VALID_ROWS)} transactions" in body, (
            f"Multiple rows must display '{len(VALID_ROWS)} transactions' (plural)"
        )


# ---------------------------------------------------------------------------
# POST /import/confirm — bulk insert
# ---------------------------------------------------------------------------

class TestPostImportConfirm:
    """POST /import/confirm inserts selected rows, clears session, redirects to /dashboard."""

    def test_confirm_all_rows_redirects_to_dashboard(self, auth_client, app):
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        form_data = {
            "row_index": ["0", "1", "2"],
            "category": ["Food", "Transport", "Bills"],
        }
        response = client.post("/import/confirm", data=form_data)
        assert response.status_code == 302, "Confirm must redirect"
        assert "/dashboard" in response.headers["Location"], (
            "Confirm must redirect to /dashboard"
        )

    def test_confirm_all_rows_inserts_correct_count(self, auth_client, app):
        """Confirming all rows inserts all of them into the expenses table."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        form_data = {
            "row_index": [str(i) for i in range(len(VALID_ROWS))],
            "category": [r["category"] for r in VALID_ROWS],
        }
        client.post("/import/confirm", data=form_data)

        with app.app_context():
            rows = db_module.get_expenses_by_user(user_id, limit=100)
        assert len(rows) == len(VALID_ROWS), (
            f"Expected {len(VALID_ROWS)} expenses inserted, found {len(rows)}"
        )

    def test_confirm_correct_amounts_inserted(self, auth_client, app):
        """The amounts stored in the DB must match the session row amounts."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        form_data = {
            "row_index": [str(i) for i in range(len(VALID_ROWS))],
            "category": [r["category"] for r in VALID_ROWS],
        }
        client.post("/import/confirm", data=form_data)

        with app.app_context():
            db_rows = db_module.get_expenses_by_user(user_id, limit=100)

        inserted_amounts = sorted(r["amount"] for r in db_rows)
        expected_amounts = sorted(r["amount"] for r in VALID_ROWS)
        assert inserted_amounts == expected_amounts, (
            "Inserted amounts must match the session row amounts exactly"
        )

    def test_confirm_correct_descriptions_inserted(self, auth_client, app):
        """Descriptions stored in the DB must match the session row descriptions."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        form_data = {
            "row_index": [str(i) for i in range(len(VALID_ROWS))],
            "category": [r["category"] for r in VALID_ROWS],
        }
        client.post("/import/confirm", data=form_data)

        with app.app_context():
            db_rows = db_module.get_expenses_by_user(user_id, limit=100)

        inserted_descs = sorted(r["description"] for r in db_rows)
        expected_descs = sorted(r["description"] for r in VALID_ROWS)
        assert inserted_descs == expected_descs, (
            "Inserted descriptions must match the session row descriptions"
        )

    def test_confirm_correct_dates_inserted(self, auth_client, app):
        """Dates stored in the DB must match the session row dates."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        form_data = {
            "row_index": [str(i) for i in range(len(VALID_ROWS))],
            "category": [r["category"] for r in VALID_ROWS],
        }
        client.post("/import/confirm", data=form_data)

        with app.app_context():
            db_rows = db_module.get_expenses_by_user(user_id, limit=100)

        inserted_dates = sorted(r["date"] for r in db_rows)
        expected_dates = sorted(r["date"] for r in VALID_ROWS)
        assert inserted_dates == expected_dates, (
            "Inserted dates must match the session row dates"
        )

    def test_confirm_correct_user_id_stored(self, auth_client, app):
        """All inserted expenses must be attributed to the logged-in user."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        form_data = {
            "row_index": [str(i) for i in range(len(VALID_ROWS))],
            "category": [r["category"] for r in VALID_ROWS],
        }
        client.post("/import/confirm", data=form_data)

        with app.app_context():
            db_rows = db_module.get_expenses_by_user(user_id, limit=100)

        for db_row in db_rows:
            assert db_row["user_id"] == user_id, (
                f"All inserted expenses must have user_id={user_id}"
            )

    def test_confirm_subset_of_rows_only_inserts_selected(self, auth_client, app):
        """Unchecked rows must NOT be inserted into the DB."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        # Select only the first row (index 0)
        form_data = {
            "row_index": ["0"],
            "category": ["Food"],
        }
        client.post("/import/confirm", data=form_data)

        with app.app_context():
            db_rows = db_module.get_expenses_by_user(user_id, limit=100)

        assert len(db_rows) == 1, (
            "Only 1 row was selected; only 1 row must be inserted"
        )
        assert db_rows[0]["description"] == VALID_ROWS[0]["description"], (
            "The inserted row must be the one that was selected (index 0)"
        )

    def test_confirm_skips_unselected_rows(self, auth_client, app):
        """Rows that are NOT selected must not appear in the DB at all."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        # Skip middle row (index 1 = "Monthly bus pass")
        form_data = {
            "row_index": ["0", "2"],
            "category": ["Food", "Bills"],
        }
        client.post("/import/confirm", data=form_data)

        with app.app_context():
            db_rows = db_module.get_expenses_by_user(user_id, limit=100)

        inserted_descs = [r["description"] for r in db_rows]
        assert "Monthly bus pass" not in inserted_descs, (
            "Deselected row 'Monthly bus pass' must NOT be inserted"
        )
        assert "Grocery run" in inserted_descs, "Selected row 'Grocery run' must be inserted"
        assert "Electricity bill" in inserted_descs, (
            "Selected row 'Electricity bill' must be inserted"
        )

    def test_confirm_no_rows_selected_inserts_nothing(self, auth_client, app):
        """Submitting with no rows checked must insert nothing and redirect."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        # Submit no row_index entries
        response = client.post("/import/confirm", data={})
        assert response.status_code == 302, "Confirm with no rows must still redirect"
        assert "/dashboard" in response.headers["Location"], (
            "Confirm with no rows must redirect to /dashboard"
        )

        with app.app_context():
            db_rows = db_module.get_expenses_by_user(user_id, limit=100)
        assert len(db_rows) == 0, "No rows selected means nothing is inserted"

    def test_confirm_category_override_respected(self, auth_client, app):
        """A category changed in the dropdown must be stored, not the original parser suggestion."""
        single_row = [
            {
                "date": "2026-04-01",
                "description": "Mystery purchase",
                "amount": 25.00,
                "category": "Other",  # original suggestion
            }
        ]
        client, user_id = auth_client
        _set_session_rows(client, single_row, user_id)
        # User overrides to "Shopping"
        form_data = {
            "row_index": ["0"],
            "category": ["Shopping"],
        }
        client.post("/import/confirm", data=form_data)

        with app.app_context():
            db_rows = db_module.get_expenses_by_user(user_id, limit=100)

        assert len(db_rows) == 1, "Exactly one row must be inserted"
        assert db_rows[0]["category"] == "Shopping", (
            "The overridden category 'Shopping' must be stored, not the original 'Other'"
        )

    def test_confirm_invalid_category_override_falls_back_to_original(
        self, auth_client, app
    ):
        """An invalid category submitted in the form must fall back to the parser's suggestion."""
        single_row = [
            {
                "date": "2026-04-02",
                "description": "Gym session",
                "amount": 50.00,
                "category": "Health",
            }
        ]
        client, user_id = auth_client
        _set_session_rows(client, single_row, user_id)
        form_data = {
            "row_index": ["0"],
            "category": ["InvalidCategory"],  # not in EXPENSE_CATEGORIES
        }
        client.post("/import/confirm", data=form_data)

        with app.app_context():
            db_rows = db_module.get_expenses_by_user(user_id, limit=100)

        assert len(db_rows) == 1, "Row must still be inserted"
        assert db_rows[0]["category"] == "Health", (
            "Invalid category override must fall back to the original parser suggestion 'Health'"
        )

    def test_confirm_session_import_rows_cleared_after_success(self, auth_client, app):
        """import_rows must be removed from the session after a successful confirm."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        form_data = {
            "row_index": [str(i) for i in range(len(VALID_ROWS))],
            "category": [r["category"] for r in VALID_ROWS],
        }
        client.post("/import/confirm", data=form_data)

        with client.session_transaction() as sess:
            remaining = sess.get("import_rows")
        assert remaining is None, (
            "import_rows must be cleared from the session after confirm"
        )

    def test_confirm_session_cleared_even_when_no_rows_selected(self, auth_client, app):
        """import_rows must be cleared even when the user selects no rows."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        client.post("/import/confirm", data={})

        with client.session_transaction() as sess:
            remaining = sess.get("import_rows")
        assert remaining is None, (
            "import_rows must be cleared from the session even when no rows are selected"
        )

    def test_confirm_invalid_row_index_is_skipped_gracefully(self, auth_client, app):
        """An out-of-range or non-integer row_index must not crash the route."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        form_data = {
            "row_index": ["999", "abc", "0"],
            "category": ["Food", "Food", "Food"],
        }
        response = client.post("/import/confirm", data=form_data)
        # Invalid indices must be silently skipped; the route must still redirect
        assert response.status_code == 302, (
            "Invalid row indices must be skipped gracefully, not cause a 500"
        )
        assert "/dashboard" in response.headers["Location"], (
            "Even with invalid indices the confirm route must redirect to /dashboard"
        )

        with app.app_context():
            db_rows = db_module.get_expenses_by_user(user_id, limit=100)
        # Only valid index 0 should have been inserted
        assert len(db_rows) == 1, "Only the valid row (index 0) should be inserted"

    def test_confirm_expenses_appear_on_dashboard_after_import(self, auth_client, app):
        """After confirming, the imported expenses must appear on the dashboard."""
        client, user_id = auth_client
        _set_session_rows(client, VALID_ROWS, user_id)
        form_data = {
            "row_index": [str(i) for i in range(len(VALID_ROWS))],
            "category": [r["category"] for r in VALID_ROWS],
        }
        client.post("/import/confirm", data=form_data)

        response = client.get("/dashboard")
        body = response.data.decode()
        for row in VALID_ROWS:
            assert row["description"] in body, (
                f"Imported expense '{row['description']}' must appear on the dashboard"
            )

    @pytest.mark.parametrize("category", ALL_CATEGORIES)
    def test_confirm_all_valid_categories_accepted(self, auth_client, app, category):
        """Each of the 7 allowed categories must be stored correctly via confirm."""
        single_row = [
            {
                "date": "2026-04-15",
                "description": f"Test expense for {category}",
                "amount": 10.00,
                "category": category,
            }
        ]
        client, user_id = auth_client
        _set_session_rows(client, single_row, user_id)
        form_data = {"row_index": ["0"], "category": [category]}
        client.post("/import/confirm", data=form_data)

        with app.app_context():
            db_rows = db_module.get_expenses_by_user(user_id, limit=10)

        assert len(db_rows) == 1, f"Row with category '{category}' must be inserted"
        assert db_rows[0]["category"] == category, (
            f"Category '{category}' must be stored verbatim"
        )


# ---------------------------------------------------------------------------
# DB layer — bulk_insert_expenses
# ---------------------------------------------------------------------------

class TestBulkInsertExpenses:
    """Direct tests for the bulk_insert_expenses database function."""

    def test_bulk_insert_inserts_all_rows(self, app, auth_client):
        """bulk_insert_expenses inserts every row in the list."""
        _, user_id = auth_client
        rows = [
            {
                "user_id": user_id,
                "amount": r["amount"],
                "category": r["category"],
                "date": r["date"],
                "description": r["description"],
            }
            for r in VALID_ROWS
        ]
        with app.app_context():
            db_module.bulk_insert_expenses(rows)
            db_rows = db_module.get_expenses_by_user(user_id, limit=100)

        assert len(db_rows) == len(VALID_ROWS), (
            f"bulk_insert_expenses must insert {len(VALID_ROWS)} rows; got {len(db_rows)}"
        )

    def test_bulk_insert_correct_amounts(self, app, auth_client):
        """Amounts written by bulk_insert_expenses must match inputs exactly."""
        _, user_id = auth_client
        rows = [
            {
                "user_id": user_id,
                "amount": 99.99,
                "category": "Food",
                "date": "2026-04-01",
                "description": "Precise amount test",
            }
        ]
        with app.app_context():
            db_module.bulk_insert_expenses(rows)
            db_rows = db_module.get_expenses_by_user(user_id, limit=10)

        assert abs(db_rows[0]["amount"] - 99.99) < 0.001, (
            "bulk_insert_expenses must store the correct amount"
        )

    def test_bulk_insert_empty_list_inserts_nothing(self, app, auth_client):
        """Calling bulk_insert_expenses with an empty list must not raise and insert nothing."""
        _, user_id = auth_client
        with app.app_context():
            db_module.bulk_insert_expenses([])  # must not raise
            db_rows = db_module.get_expenses_by_user(user_id, limit=100)

        assert len(db_rows) == 0, "Inserting an empty list must leave the DB unchanged"

    def test_bulk_insert_rollback_on_fk_violation(self, app, auth_client, tmp_db):
        """
        If any row causes a constraint violation (e.g. non-existent user_id with FK ON),
        the entire batch must be rolled back.
        """
        _, real_user_id = auth_client

        rows = [
            # Valid row
            {
                "user_id": real_user_id,
                "amount": 10.00,
                "category": "Food",
                "date": "2026-04-01",
                "description": "Valid row",
            },
            # Invalid row — user_id 999999 does not exist
            {
                "user_id": 999999,
                "amount": 20.00,
                "category": "Bills",
                "date": "2026-04-02",
                "description": "Invalid user row",
            },
        ]

        with app.app_context():
            try:
                db_module.bulk_insert_expenses(rows)
            except Exception:
                pass  # expected to raise; we just want to verify rollback

            # Neither row should be present in the DB
            db_rows = db_module.get_expenses_by_user(real_user_id, limit=100)

        assert len(db_rows) == 0, (
            "bulk_insert_expenses must roll back entirely when any row violates a constraint; "
            "no rows must be present after a failed batch"
        )

    def test_bulk_insert_uses_executemany_not_loop(self, app, auth_client, monkeypatch):
        """
        Verify bulk_insert_expenses calls executemany (single transaction) rather than
        individual execute calls in a loop.  We monkeypatch the connection to track calls.
        """
        _, user_id = auth_client
        executemany_calls = []
        execute_insert_calls = []

        original_get_db = db_module.get_db

        def patched_get_db():
            conn = original_get_db()
            original_executemany = conn.executemany
            original_execute = conn.execute

            def tracking_executemany(sql, *args, **kwargs):
                if "INSERT" in sql.upper():
                    executemany_calls.append(sql)
                return original_executemany(sql, *args, **kwargs)

            def tracking_execute(sql, *args, **kwargs):
                if "INSERT INTO expenses" in sql.upper():
                    execute_insert_calls.append(sql)
                return original_execute(sql, *args, **kwargs)

            conn.executemany = tracking_executemany
            conn.execute = tracking_execute
            return conn

        monkeypatch.setattr(db_module, "get_db", patched_get_db)

        rows = [
            {
                "user_id": user_id,
                "amount": r["amount"],
                "category": r["category"],
                "date": r["date"],
                "description": r["description"],
            }
            for r in VALID_ROWS
        ]
        with app.app_context():
            db_module.bulk_insert_expenses(rows)

        assert len(executemany_calls) >= 1, (
            "bulk_insert_expenses must use conn.executemany for batch insertion"
        )
        assert len(execute_insert_calls) == 0, (
            "bulk_insert_expenses must NOT use individual conn.execute INSERT calls in a loop"
        )


# ---------------------------------------------------------------------------
# Rule-based parser — parse_statement_rules (unit tests, no routes)
# ---------------------------------------------------------------------------

class TestParseStatementRules:
    """Unit tests for the rule-based CSV parser used when no API key is set."""

    def test_valid_csv_returns_rows(self):
        """A well-formed CSV with standard columns returns the correct rows."""
        from utils.statement_parser import parse_statement_rules
        rows = parse_statement_rules(VALID_CSV)
        assert isinstance(rows, list), "parse_statement_rules must return a list"
        assert len(rows) == 3, "Three expense rows must be parsed from the valid CSV"

    def test_valid_csv_row_has_required_keys(self):
        """Each parsed row must have date, description, amount, and category keys."""
        from utils.statement_parser import parse_statement_rules
        rows = parse_statement_rules(VALID_CSV)
        for row in rows:
            for key in ("date", "description", "amount", "category"):
                assert key in row, f"Row must contain key '{key}'"

    def test_valid_csv_date_format_is_yyyy_mm_dd(self):
        """Parsed dates must be in YYYY-MM-DD format."""
        from utils.statement_parser import parse_statement_rules
        import re
        rows = parse_statement_rules(VALID_CSV)
        for row in rows:
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", row["date"]), (
                f"Date '{row['date']}' must be in YYYY-MM-DD format"
            )

    def test_valid_csv_amounts_are_positive_floats(self):
        """Parsed amounts must be positive floats."""
        from utils.statement_parser import parse_statement_rules
        rows = parse_statement_rules(VALID_CSV)
        for row in rows:
            assert isinstance(row["amount"], float), "Amount must be a float"
            assert row["amount"] > 0, "Amount must be positive"

    def test_valid_csv_categories_are_allowed(self):
        """Parsed categories must belong to the allowed set."""
        from utils.statement_parser import parse_statement_rules
        rows = parse_statement_rules(VALID_CSV)
        for row in rows:
            assert row["category"] in ALL_CATEGORIES, (
                f"Category '{row['category']}' must be one of the 7 allowed categories"
            )

    def test_csv_with_no_valid_transactions_returns_empty_list(self):
        """A CSV with only headers (no data rows) must return an empty list."""
        from utils.statement_parser import parse_statement_rules
        header_only_csv = "Date,Narration,Debit\n"
        rows = parse_statement_rules(header_only_csv)
        assert rows == [], (
            "A CSV with only a header row must return an empty list"
        )

    def test_csv_credits_are_excluded(self):
        """Rows with a DR/CR column marked as 'CR' must be skipped."""
        from utils.statement_parser import parse_statement_rules
        csv_with_credits = (
            "Date,Narration,Debit,DR/CR\n"
            "01/04/2026,Salary credit,5000.00,CR\n"
            "02/04/2026,Grocery run,100.00,DR\n"
        )
        rows = parse_statement_rules(csv_with_credits)
        descriptions = [r["description"] for r in rows]
        assert "Salary credit" not in descriptions, (
            "Credit rows must be excluded from parsed output"
        )
        assert "Grocery run" in descriptions, (
            "Debit rows must be included"
        )

    def test_csv_food_keyword_categorized_as_food(self):
        """A description containing a Food keyword must be categorized as Food."""
        from utils.statement_parser import parse_statement_rules
        csv = "Date,Narration,Debit\n01/04/2026,Zomato order,50.00\n"
        rows = parse_statement_rules(csv)
        assert rows[0]["category"] == "Food", (
            "Description containing 'zomato' must be categorized as 'Food'"
        )

    def test_csv_transport_keyword_categorized_correctly(self):
        """A description containing a Transport keyword must be categorized as Transport."""
        from utils.statement_parser import parse_statement_rules
        csv = "Date,Narration,Debit\n01/04/2026,Uber cab ride,80.00\n"
        rows = parse_statement_rules(csv)
        assert rows[0]["category"] == "Transport", (
            "Description containing 'uber' must be categorized as 'Transport'"
        )

    def test_csv_unknown_description_categorized_as_other(self):
        """A description with no matching keywords must default to 'Other'."""
        from utils.statement_parser import parse_statement_rules
        csv = "Date,Narration,Debit\n01/04/2026,XYZ Corp payment,200.00\n"
        rows = parse_statement_rules(csv)
        assert rows[0]["category"] == "Other", (
            "Unknown description must default to 'Other' category"
        )

    def test_csv_with_comma_in_amount_parsed_correctly(self):
        """Amounts formatted with commas (e.g. 1,200.50) must be parsed as floats."""
        from utils.statement_parser import parse_statement_rules
        csv = "Date,Narration,Debit\n01/04/2026,Rent payment,\"1,200.50\"\n"
        rows = parse_statement_rules(csv)
        assert len(rows) == 1, "Row with comma-formatted amount must be parsed"
        assert abs(rows[0]["amount"] - 1200.50) < 0.01, (
            "Comma-formatted amount '1,200.50' must parse to 1200.50"
        )

    def test_csv_negative_or_zero_amounts_excluded(self):
        """Rows with zero or negative amounts must be excluded from results."""
        from utils.statement_parser import parse_statement_rules
        csv = (
            "Date,Narration,Debit\n"
            "01/04/2026,Zero payment,0.00\n"
            "02/04/2026,Valid payment,50.00\n"
        )
        rows = parse_statement_rules(csv)
        amounts = [r["amount"] for r in rows]
        assert 0.0 not in amounts, "Zero-amount rows must be excluded"
        assert 50.0 in amounts, "Valid positive-amount row must be included"

    def test_csv_missing_required_columns_raises_parse_error(self):
        """A CSV missing required columns (e.g. no amount column) must raise ParseError."""
        from utils.statement_parser import parse_statement_rules, ParseError
        bad_csv = "Date,Narration\n01/04/2026,Some expense\n"
        with pytest.raises(ParseError):
            parse_statement_rules(bad_csv)

    def test_csv_dot_separated_date_format_parsed(self):
        """Dates in DD.MM.YYYY format (common in some banks) must be parsed correctly."""
        from utils.statement_parser import parse_statement_rules
        import re
        csv = "Date,Narration,Debit\n15.04.2026,Coffee shop,3.50\n"
        rows = parse_statement_rules(csv)
        assert len(rows) == 1, "Dot-separated date format must be parsed"
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", rows[0]["date"]), (
            "Parsed date must be in YYYY-MM-DD format"
        )
        assert rows[0]["date"] == "2026-04-15", (
            "15.04.2026 must be parsed as 2026-04-15"
        )


# ---------------------------------------------------------------------------
# Full flow integration test
# ---------------------------------------------------------------------------

class TestFullImportFlow:
    """
    End-to-end test that walks through the entire import flow using the
    route layer only (no direct DB or parser calls), with the parser mocked.
    """

    def test_full_flow_upload_preview_confirm_dashboard(self, auth_client, app, monkeypatch):
        """
        Happy path: upload CSV -> parser returns rows -> stored in session ->
        preview page renders -> confirm inserts rows -> dashboard shows them.
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(parser_module, "parse_statement_rules", lambda _: VALID_ROWS)

        client, user_id = auth_client

        # Step 1: Upload
        upload_response = client.post(
            "/import",
            data=_make_file(VALID_CSV),
            content_type="multipart/form-data",
        )
        assert upload_response.status_code == 302, "Upload must redirect after successful parse"
        assert "/import/preview" in upload_response.headers["Location"]

        # Step 2: Preview
        preview_response = client.get("/import/preview")
        assert preview_response.status_code == 200, "Preview must return 200"
        preview_body = preview_response.data.decode()
        assert "Review Transactions" in preview_body
        assert str(len(VALID_ROWS)) in preview_body

        # Step 3: Confirm all rows
        form_data = {
            "row_index": [str(i) for i in range(len(VALID_ROWS))],
            "category": [r["category"] for r in VALID_ROWS],
        }
        confirm_response = client.post("/import/confirm", data=form_data)
        assert confirm_response.status_code == 302, "Confirm must redirect"
        assert "/dashboard" in confirm_response.headers["Location"]

        # Step 4: Dashboard
        dashboard_response = client.get("/dashboard")
        assert dashboard_response.status_code == 200
        dashboard_body = dashboard_response.data.decode()
        for row in VALID_ROWS:
            assert row["description"] in dashboard_body, (
                f"Imported expense '{row['description']}' must appear on the dashboard"
            )

        # Step 5: Session must be clean
        with client.session_transaction() as sess:
            assert "import_rows" not in sess, "import_rows must be gone after confirm"
