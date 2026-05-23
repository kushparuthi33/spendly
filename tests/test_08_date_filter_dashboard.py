"""
Tests for the Date Filter Dashboard feature (Spec 08).

Spec: .claude/specs/08-date-filter-dashboard.md

All tests hit the HTTP surface via Flask's test client.
An isolated temporary SQLite DB is used per test — the real spendly.db is never touched.
Expense records with known, controlled dates are inserted so filter assertions are deterministic.

Today's date as seen by the tests = the real calendar date at test-run time.  Tests that
depend on relative ranges (this_month, last_3_months, last_6_months) compute those ranges
in the same way the route does, so they stay valid on any run date.
"""

import sqlite3
from datetime import date, timedelta

import pytest

import database.db as db_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_expense(app, user_id, amount, category, exp_date, description=""):
    """Insert a single expense directly via db helper within an app context."""
    with app.app_context():
        return db_module.create_expense(user_id, amount, category, exp_date, description)


def _insert_expenses_bulk(app, rows):
    """Insert multiple expenses. Each row is a dict with keys matching create_expense args."""
    with app.app_context():
        for r in rows:
            db_module.create_expense(
                r["user_id"], r["amount"], r["category"], r["date"], r.get("description", "")
            )


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

class TestAuthGuard:
    def test_unauthenticated_dashboard_redirects_to_login(self, client):
        """GET /dashboard without a session must redirect to /login (302)."""
        response = client.get("/dashboard")
        assert response.status_code == 302, "Expected 302 redirect for unauthenticated user"
        assert "/login" in response.headers["Location"], (
            "Redirect target should be the login page"
        )

    def test_unauthenticated_dashboard_with_preset_redirects(self, client):
        """Even with query params, unauthenticated requests redirect to login."""
        response = client.get("/dashboard?preset=this_month")
        assert response.status_code == 302, "Expected redirect regardless of query params"
        assert "/login" in response.headers["Location"], "Should redirect to login"

    def test_unauthenticated_dashboard_with_custom_dates_redirects(self, client):
        """Custom date params do not bypass the auth guard."""
        response = client.get("/dashboard?from_date=2026-01-01&to_date=2026-12-31")
        assert response.status_code == 302, "Expected redirect for unauthenticated custom date request"
        assert "/login" in response.headers["Location"], "Should redirect to login"


# ---------------------------------------------------------------------------
# Baseline — no query params
# ---------------------------------------------------------------------------

class TestNoQueryParams:
    def test_dashboard_no_params_returns_200(self, auth_client, app):
        """GET /dashboard with no params returns HTTP 200 for a logged-in user."""
        client, user_id = auth_client
        response = client.get("/dashboard")
        assert response.status_code == 200, "Dashboard should return 200 for authenticated user"

    def test_dashboard_no_params_renders_template_landmarks(self, auth_client, app):
        """Dashboard with no params renders the filter bar and stat card landmarks."""
        client, user_id = auth_client
        response = client.get("/dashboard")
        body = response.data.decode()
        assert "filter-bar" in body, "Filter bar container must be present"
        assert "filter-presets" in body, "Preset links container must be present"
        assert "Total Spent" in body, "Total Spent stat card must be rendered"
        assert "Total Expenses" in body, "Total Expenses stat card must be rendered"
        assert "Top Category" in body, "Top Category stat card must be rendered"

    def test_dashboard_no_params_shows_all_time_preset_active(self, auth_client, app):
        """With no query params the 'All time' preset link carries is-active."""
        client, user_id = auth_client
        response = client.get("/dashboard")
        body = response.data.decode()
        # The template renders is-active on the All time link when no filter is set
        assert "is-active" in body, "At least one preset must be marked is-active"
        # Verify the All time preset is the active one by checking proximity of text
        # The template does: class="filter-preset {{ 'is-active' if ... }}">All time
        assert "All time" in body, "All time preset must be visible"
        # The is-active class must appear on the All-time link, not on others
        # We check that the fragment containing "All time" also contains is-active
        all_time_section = body[body.rfind("All time") - 200 : body.rfind("All time") + 20]
        assert "is-active" in all_time_section, (
            "The 'All time' preset link must have is-active class when no filter is applied"
        )

    def test_dashboard_no_params_no_active_filter_label(self, auth_client, app):
        """With no query params, the 'Showing:' active-filter label must NOT appear."""
        client, user_id = auth_client
        response = client.get("/dashboard")
        body = response.data.decode()
        assert "Showing:" not in body, (
            "'Showing:' label must not appear when no date filter is active"
        )

    def test_dashboard_no_params_shows_all_expenses(self, auth_client, app):
        """With no filter, all inserted expenses (up to 30) are visible."""
        client, user_id = auth_client
        today = date.today()
        old_date = (today - timedelta(days=400)).strftime("%Y-%m-%d")
        recent_date = today.strftime("%Y-%m-%d")

        _insert_expense(app, user_id, 10.00, "Food", old_date, "Old expense")
        _insert_expense(app, user_id, 20.00, "Bills", recent_date, "Recent expense")

        response = client.get("/dashboard")
        body = response.data.decode()
        assert "Old expense" in body, "Expense from over a year ago must appear with no filter"
        assert "Recent expense" in body, "Recent expense must appear with no filter"

    def test_dashboard_no_params_30_row_limit(self, auth_client, app):
        """With no filter the expense table is still limited to 30 rows."""
        client, user_id = auth_client
        today = date.today().strftime("%Y-%m-%d")
        # Insert 35 expenses
        for i in range(35):
            _insert_expense(app, user_id, float(i + 1), "Food", today, f"Expense {i + 1:02d}")

        response = client.get("/dashboard")
        body = response.data.decode()
        # Count table rows in the expense table body by counting occurrences of
        # the amount cell pattern — each expense renders one <tr> with an amount
        count = body.count("amount-cell")
        assert count <= 30, f"Expected at most 30 expense rows, got {count}"
        assert count == 30, f"Expected exactly 30 expense rows to respect the LIMIT, got {count}"


# ---------------------------------------------------------------------------
# this_month preset
# ---------------------------------------------------------------------------

class TestThisMonthPreset:
    def test_this_month_returns_200(self, auth_client, app):
        client, _ = auth_client
        response = client.get("/dashboard?preset=this_month")
        assert response.status_code == 200, "?preset=this_month must return 200"

    def test_this_month_preset_link_is_active(self, auth_client, app):
        """The 'This month' preset link carries is-active; others do not."""
        client, user_id = auth_client
        response = client.get("/dashboard?preset=this_month")
        body = response.data.decode()

        # Locate each preset link and check active state
        this_month_idx = body.find("This month")
        last_3_idx = body.find("Last 3 months")
        last_6_idx = body.find("Last 6 months")
        all_time_idx = body.rfind("All time")

        # The is-active class appears in the anchor tag just before the link text
        def has_active_class_near(idx, window=150):
            snippet = body[max(0, idx - window): idx]
            return "is-active" in snippet

        assert has_active_class_near(this_month_idx), (
            "'This month' link must have is-active class"
        )
        assert not has_active_class_near(last_3_idx), (
            "'Last 3 months' link must NOT have is-active when this_month is selected"
        )
        assert not has_active_class_near(last_6_idx), (
            "'Last 6 months' link must NOT have is-active when this_month is selected"
        )
        assert not has_active_class_near(all_time_idx), (
            "'All time' link must NOT have is-active when this_month is selected"
        )

    def test_this_month_shows_active_label(self, auth_client, app):
        """When this_month is active, a 'Showing:' label must appear."""
        client, user_id = auth_client
        _insert_expense(app, user_id, 50.00, "Food", date.today().strftime("%Y-%m-%d"), "today's expense")
        response = client.get("/dashboard?preset=this_month")
        body = response.data.decode()
        assert "Showing:" in body, "Active filter label 'Showing:' must appear for this_month preset"

    def test_this_month_shows_clear_link(self, auth_client, app):
        """A 'Clear' link must be present when this_month filter is active."""
        client, user_id = auth_client
        _insert_expense(app, user_id, 50.00, "Food", date.today().strftime("%Y-%m-%d"), "today")
        response = client.get("/dashboard?preset=this_month")
        body = response.data.decode()
        assert "Clear" in body, "A 'Clear' link must appear when a preset filter is active"
        assert "/dashboard" in body, "Clear link must point back to the dashboard (no filter)"

    def test_this_month_excludes_old_expenses(self, auth_client, app):
        """Expenses outside the current month must NOT appear in the expense table."""
        client, user_id = auth_client
        today = date.today()
        first_of_month = date(today.year, today.month, 1)
        old_date = (first_of_month - timedelta(days=1)).strftime("%Y-%m-%d")
        this_month_date = today.strftime("%Y-%m-%d")

        _insert_expense(app, user_id, 99.99, "Bills", old_date, "Last month bill")
        _insert_expense(app, user_id, 11.11, "Food", this_month_date, "This month snack")

        response = client.get("/dashboard?preset=this_month")
        body = response.data.decode()
        assert "This month snack" in body, "Expense from this month must appear"
        assert "Last month bill" not in body, (
            "Expense from before this month must NOT appear under this_month filter"
        )

    def test_this_month_stats_reflect_filtered_range(self, auth_client, app):
        """Total Spent and expense count must reflect only this month's expenses."""
        client, user_id = auth_client
        today = date.today()
        first_of_month = date(today.year, today.month, 1)
        old_date = (first_of_month - timedelta(days=5)).strftime("%Y-%m-%d")
        this_month_date = today.strftime("%Y-%m-%d")

        _insert_expense(app, user_id, 500.00, "Bills", old_date, "Old big bill")
        _insert_expense(app, user_id, 42.00, "Food", this_month_date, "This month food")

        response = client.get("/dashboard?preset=this_month")
        body = response.data.decode()
        # Total spent of 500.00 must NOT appear; 42.00 must appear
        assert "42.00" in body, "This month's total (42.00) must appear in stats"
        assert "500.00" not in body, (
            "Old expense amount (500.00) must not affect stats under this_month filter"
        )

    def test_this_month_category_totals_reflect_filtered_range(self, auth_client, app):
        """Category totals must reflect only this month when the filter is active."""
        client, user_id = auth_client
        today = date.today()
        first_of_month = date(today.year, today.month, 1)
        old_date = (first_of_month - timedelta(days=10)).strftime("%Y-%m-%d")
        this_month_date = today.strftime("%Y-%m-%d")

        # Old expense in Transport — should NOT appear in category totals
        _insert_expense(app, user_id, 200.00, "Transport", old_date, "Old transport")
        # This month expense in Health — MUST appear
        _insert_expense(app, user_id, 77.50, "Health", this_month_date, "Gym membership")

        response = client.get("/dashboard?preset=this_month")
        body = response.data.decode()
        assert "77.50" in body, "This month category amount (77.50) must appear"
        assert "200.00" not in body, (
            "Category amount from before this month (200.00) must not appear"
        )


# ---------------------------------------------------------------------------
# last_3_months preset
# ---------------------------------------------------------------------------

class TestLast3MonthsPreset:
    def test_last_3_months_returns_200(self, auth_client, app):
        client, _ = auth_client
        response = client.get("/dashboard?preset=last_3_months")
        assert response.status_code == 200, "?preset=last_3_months must return 200"

    def test_last_3_months_preset_link_is_active(self, auth_client, app):
        """'Last 3 months' link has is-active; other presets do not."""
        client, user_id = auth_client
        response = client.get("/dashboard?preset=last_3_months")
        body = response.data.decode()

        last_3_idx = body.find("Last 3 months")
        this_month_idx = body.find("This month")
        all_time_idx = body.rfind("All time")

        def has_active_class_near(idx, window=150):
            snippet = body[max(0, idx - window): idx]
            return "is-active" in snippet

        assert has_active_class_near(last_3_idx), "'Last 3 months' must have is-active"
        assert not has_active_class_near(this_month_idx), (
            "'This month' must NOT have is-active when last_3_months is selected"
        )
        assert not has_active_class_near(all_time_idx), (
            "'All time' must NOT have is-active when last_3_months is selected"
        )

    def test_last_3_months_shows_active_label(self, auth_client, app):
        client, user_id = auth_client
        _insert_expense(app, user_id, 10.00, "Food", date.today().strftime("%Y-%m-%d"), "today")
        response = client.get("/dashboard?preset=last_3_months")
        body = response.data.decode()
        assert "Showing:" in body, "'Showing:' label must appear for last_3_months preset"

    def test_last_3_months_excludes_expenses_older_than_90_days(self, auth_client, app):
        """Expenses older than 90 days must NOT appear under last_3_months."""
        client, user_id = auth_client
        today = date.today()
        within_range = (today - timedelta(days=89)).strftime("%Y-%m-%d")
        outside_range = (today - timedelta(days=91)).strftime("%Y-%m-%d")

        _insert_expense(app, user_id, 33.33, "Food", within_range, "Within 90 days")
        _insert_expense(app, user_id, 99.00, "Bills", outside_range, "Outside 90 days")

        response = client.get("/dashboard?preset=last_3_months")
        body = response.data.decode()
        assert "Within 90 days" in body, "Expense within 90 days must appear"
        assert "Outside 90 days" not in body, "Expense older than 90 days must NOT appear"

    def test_last_3_months_includes_expense_exactly_90_days_ago(self, auth_client, app):
        """Expense exactly 90 days ago must be included (boundary inclusive)."""
        client, user_id = auth_client
        today = date.today()
        boundary_date = (today - timedelta(days=90)).strftime("%Y-%m-%d")

        _insert_expense(app, user_id, 55.55, "Health", boundary_date, "Boundary expense")

        response = client.get("/dashboard?preset=last_3_months")
        body = response.data.decode()
        assert "Boundary expense" in body, "Expense exactly 90 days ago must appear (inclusive boundary)"

    def test_last_3_months_stats_reflect_filtered_range(self, auth_client, app):
        """Total Spent reflects only the last 90 days."""
        client, user_id = auth_client
        today = date.today()
        within = today.strftime("%Y-%m-%d")
        outside = (today - timedelta(days=100)).strftime("%Y-%m-%d")

        _insert_expense(app, user_id, 123.45, "Shopping", within, "Recent shopping")
        _insert_expense(app, user_id, 678.90, "Bills", outside, "Old big bill")

        response = client.get("/dashboard?preset=last_3_months")
        body = response.data.decode()
        assert "123.45" in body, "Recent total must appear"
        assert "678.90" not in body, "Old total must not appear in stats"


# ---------------------------------------------------------------------------
# last_6_months preset
# ---------------------------------------------------------------------------

class TestLast6MonthsPreset:
    def test_last_6_months_returns_200(self, auth_client, app):
        client, _ = auth_client
        response = client.get("/dashboard?preset=last_6_months")
        assert response.status_code == 200, "?preset=last_6_months must return 200"

    def test_last_6_months_preset_link_is_active(self, auth_client, app):
        """'Last 6 months' link has is-active; other presets do not."""
        client, user_id = auth_client
        response = client.get("/dashboard?preset=last_6_months")
        body = response.data.decode()

        last_6_idx = body.find("Last 6 months")
        this_month_idx = body.find("This month")
        all_time_idx = body.rfind("All time")

        def has_active_class_near(idx, window=150):
            return "is-active" in body[max(0, idx - window): idx]

        assert has_active_class_near(last_6_idx), "'Last 6 months' must have is-active"
        assert not has_active_class_near(this_month_idx), (
            "'This month' must NOT have is-active when last_6_months is selected"
        )
        assert not has_active_class_near(all_time_idx), (
            "'All time' must NOT have is-active when last_6_months is selected"
        )

    def test_last_6_months_shows_active_label(self, auth_client, app):
        client, user_id = auth_client
        _insert_expense(app, user_id, 10.00, "Food", date.today().strftime("%Y-%m-%d"), "today")
        response = client.get("/dashboard?preset=last_6_months")
        body = response.data.decode()
        assert "Showing:" in body, "'Showing:' label must appear for last_6_months preset"

    def test_last_6_months_excludes_expenses_older_than_180_days(self, auth_client, app):
        """Expenses older than 180 days must NOT appear under last_6_months."""
        client, user_id = auth_client
        today = date.today()
        within_range = (today - timedelta(days=179)).strftime("%Y-%m-%d")
        outside_range = (today - timedelta(days=181)).strftime("%Y-%m-%d")

        _insert_expense(app, user_id, 44.44, "Entertainment", within_range, "Within 180 days")
        _insert_expense(app, user_id, 88.88, "Bills", outside_range, "Outside 180 days")

        response = client.get("/dashboard?preset=last_6_months")
        body = response.data.decode()
        assert "Within 180 days" in body, "Expense within 180 days must appear"
        assert "Outside 180 days" not in body, "Expense older than 180 days must NOT appear"

    def test_last_6_months_includes_expense_exactly_180_days_ago(self, auth_client, app):
        """Expense exactly 180 days ago must be included (inclusive boundary)."""
        client, user_id = auth_client
        today = date.today()
        boundary_date = (today - timedelta(days=180)).strftime("%Y-%m-%d")

        _insert_expense(app, user_id, 66.66, "Other", boundary_date, "6month boundary")

        response = client.get("/dashboard?preset=last_6_months")
        body = response.data.decode()
        assert "6month boundary" in body, "Expense exactly 180 days ago must be included"

    def test_last_6_months_stats_reflect_filtered_range(self, auth_client, app):
        """Total Spent and count reflect only the last 180 days."""
        client, user_id = auth_client
        today = date.today()
        within = (today - timedelta(days=50)).strftime("%Y-%m-%d")
        outside = (today - timedelta(days=200)).strftime("%Y-%m-%d")

        _insert_expense(app, user_id, 222.22, "Food", within, "Recent")
        _insert_expense(app, user_id, 999.99, "Bills", outside, "Ancient")

        response = client.get("/dashboard?preset=last_6_months")
        body = response.data.decode()
        assert "222.22" in body, "Recent total must appear"
        assert "999.99" not in body, "Ancient total must not appear in filtered stats"


# ---------------------------------------------------------------------------
# all_time preset (explicit)
# ---------------------------------------------------------------------------

class TestAllTimePreset:
    def test_all_time_preset_returns_200(self, auth_client, app):
        client, _ = auth_client
        response = client.get("/dashboard?preset=all_time")
        assert response.status_code == 200, "?preset=all_time must return 200"

    def test_all_time_preset_shows_all_expenses(self, auth_client, app):
        """?preset=all_time shows expenses from any date."""
        client, user_id = auth_client
        today = date.today()
        old = (today - timedelta(days=500)).strftime("%Y-%m-%d")
        recent = today.strftime("%Y-%m-%d")

        _insert_expense(app, user_id, 11.00, "Food", old, "Very old food")
        _insert_expense(app, user_id, 22.00, "Food", recent, "Today food")

        response = client.get("/dashboard?preset=all_time")
        body = response.data.decode()
        assert "Very old food" in body, "Very old expense must appear under all_time preset"
        assert "Today food" in body, "Recent expense must appear under all_time preset"

    def test_all_time_preset_no_active_label(self, auth_client, app):
        """?preset=all_time must NOT show the 'Showing:' active-filter label."""
        client, _ = auth_client
        response = client.get("/dashboard?preset=all_time")
        body = response.data.decode()
        assert "Showing:" not in body, (
            "'Showing:' label must not appear for all_time preset (no date restriction)"
        )

    def test_all_time_preset_link_is_active(self, auth_client, app):
        """With ?preset=all_time, the 'All time' link has is-active."""
        client, _ = auth_client
        response = client.get("/dashboard?preset=all_time")
        body = response.data.decode()
        all_time_idx = body.rfind("All time")
        snippet = body[max(0, all_time_idx - 200): all_time_idx]
        assert "is-active" in snippet, "'All time' must have is-active for preset=all_time"


# ---------------------------------------------------------------------------
# Custom date range
# ---------------------------------------------------------------------------

class TestCustomDateRange:
    def test_custom_range_returns_200(self, auth_client, app):
        client, _ = auth_client
        response = client.get("/dashboard?from_date=2025-01-01&to_date=2025-12-31")
        assert response.status_code == 200, "Custom date range must return 200"

    def test_custom_range_filters_expenses(self, auth_client, app):
        """Only expenses within the custom range appear in the expense table."""
        client, user_id = auth_client
        _insert_expense(app, user_id, 10.00, "Food", "2025-03-15", "March food")
        _insert_expense(app, user_id, 20.00, "Bills", "2024-12-31", "Dec bill outside")
        _insert_expense(app, user_id, 30.00, "Health", "2025-06-30", "June health")
        _insert_expense(app, user_id, 40.00, "Shopping", "2025-07-01", "July shopping outside")

        response = client.get("/dashboard?from_date=2025-01-01&to_date=2025-06-30")
        body = response.data.decode()
        assert "March food" in body, "Expense within custom range must appear"
        assert "June health" in body, "Expense on to_date boundary must appear"
        assert "Dec bill outside" not in body, "Expense before from_date must NOT appear"
        assert "July shopping outside" not in body, "Expense after to_date must NOT appear"

    def test_custom_range_shows_active_label(self, auth_client, app):
        """When a custom range is applied, 'Showing:' label with the date range appears."""
        client, user_id = auth_client
        _insert_expense(app, user_id, 10.00, "Food", "2025-04-10", "April food")

        response = client.get("/dashboard?from_date=2025-04-01&to_date=2025-04-30")
        body = response.data.decode()
        assert "Showing:" in body, "'Showing:' label must appear for custom date range"

    def test_custom_range_label_contains_formatted_dates(self, auth_client, app):
        """The 'Showing:' label displays dates in human-readable DD Mon YYYY format."""
        client, user_id = auth_client
        _insert_expense(app, user_id, 10.00, "Food", "2025-04-10", "April expense")

        response = client.get("/dashboard?from_date=2025-04-01&to_date=2025-04-30")
        body = response.data.decode()
        # The route formats as "%d %b %Y", e.g. "01 Apr 2025"
        assert "01 Apr 2025" in body, "from_date must appear formatted as DD Mon YYYY"
        assert "30 Apr 2025" in body, "to_date must appear formatted as DD Mon YYYY"

    def test_custom_range_shows_clear_link(self, auth_client, app):
        """A 'Clear' link pointing to plain /dashboard must appear when custom range is active."""
        client, user_id = auth_client
        _insert_expense(app, user_id, 10.00, "Food", "2025-06-01", "June")

        response = client.get("/dashboard?from_date=2025-06-01&to_date=2025-06-30")
        body = response.data.decode()
        assert "Clear" in body, "Clear link must appear when custom range is active"

    def test_custom_range_stats_reflect_range(self, auth_client, app):
        """Total Spent stat reflects only expenses within the custom range."""
        client, user_id = auth_client
        _insert_expense(app, user_id, 123.00, "Food", "2025-05-15", "In range")
        _insert_expense(app, user_id, 456.00, "Bills", "2024-01-01", "Out of range")

        response = client.get("/dashboard?from_date=2025-01-01&to_date=2025-12-31")
        body = response.data.decode()
        assert "123.00" in body, "In-range expense total must appear"
        assert "456.00" not in body, "Out-of-range expense total must not affect stats"

    def test_custom_range_30_row_limit_still_applies(self, auth_client, app):
        """The 30-row LIMIT still applies within a custom date range."""
        client, user_id = auth_client
        target_date = "2025-07-01"
        for i in range(35):
            _insert_expense(app, user_id, float(i + 1), "Food", target_date, f"Expense {i + 1:02d}")

        response = client.get("/dashboard?from_date=2025-07-01&to_date=2025-07-01")
        body = response.data.decode()
        count = body.count("amount-cell")
        assert count <= 30, f"Expense table must be limited to 30 rows even with a date filter, got {count}"

    def test_custom_range_from_date_after_to_date_swapped_silently(self, auth_client, app):
        """If from_date > to_date the route swaps them silently and returns 200."""
        client, user_id = auth_client
        _insert_expense(app, user_id, 55.55, "Food", "2025-06-15", "Mid June expense")

        # Deliberately pass reversed dates
        response = client.get("/dashboard?from_date=2025-06-30&to_date=2025-06-01")
        assert response.status_code == 200, "Reversed dates must not cause an error"
        body = response.data.decode()
        # After swapping, the range is 2025-06-01 to 2025-06-30, so the expense appears
        assert "Mid June expense" in body, (
            "After silent swap the correct range should be applied and expense should appear"
        )
        # The Showing label should reflect the corrected (swapped) order
        assert "Showing:" in body, "A Showing label must still appear for swapped dates"

    def test_custom_range_category_totals_filtered(self, auth_client, app):
        """Category totals only reflect expenses within the custom date range."""
        client, user_id = auth_client
        _insert_expense(app, user_id, 300.00, "Transport", "2025-08-01", "August transport")
        _insert_expense(app, user_id, 50.00, "Food", "2025-09-01", "September food")

        response = client.get("/dashboard?from_date=2025-09-01&to_date=2025-09-30")
        body = response.data.decode()
        assert "50.00" in body, "Food category total in range must appear"
        assert "300.00" not in body, "Transport from outside range must NOT appear in categories"


# ---------------------------------------------------------------------------
# Invalid date strings — fallback to all-time
# ---------------------------------------------------------------------------

class TestInvalidDates:
    def test_invalid_from_date_returns_200_not_500(self, auth_client, app):
        """Non-parseable from_date must not cause a 500 error."""
        client, _ = auth_client
        response = client.get("/dashboard?from_date=not-a-date&to_date=2025-12-31")
        assert response.status_code == 200, (
            "Invalid from_date must return 200 by falling back to all-time"
        )

    def test_invalid_to_date_returns_200_not_500(self, auth_client, app):
        """Non-parseable to_date must not cause a 500 error."""
        client, _ = auth_client
        response = client.get("/dashboard?from_date=2025-01-01&to_date=INVALID")
        assert response.status_code == 200, (
            "Invalid to_date must return 200 by falling back to all-time"
        )

    def test_both_invalid_dates_return_200(self, auth_client, app):
        """Both dates invalid — falls back to all-time with 200."""
        client, _ = auth_client
        response = client.get("/dashboard?from_date=abc&to_date=xyz")
        assert response.status_code == 200, "Both dates invalid must still return 200"

    def test_invalid_dates_no_active_label(self, auth_client, app):
        """When dates are invalid and fall back to all-time, 'Showing:' must not appear."""
        client, _ = auth_client
        response = client.get("/dashboard?from_date=bad&to_date=input")
        body = response.data.decode()
        assert "Showing:" not in body, (
            "'Showing:' must not appear when invalid dates cause a fallback to all-time"
        )

    def test_invalid_dates_show_all_expenses(self, auth_client, app):
        """Invalid date fallback shows all expenses, not a filtered subset."""
        client, user_id = auth_client
        old = (date.today() - timedelta(days=400)).strftime("%Y-%m-%d")
        recent = date.today().strftime("%Y-%m-%d")
        _insert_expense(app, user_id, 10.00, "Food", old, "Old expense fallback")
        _insert_expense(app, user_id, 20.00, "Bills", recent, "Recent expense fallback")

        response = client.get("/dashboard?from_date=garbage&to_date=garbage")
        body = response.data.decode()
        assert "Old expense fallback" in body, (
            "Old expense must appear when invalid dates cause fallback to all-time"
        )
        assert "Recent expense fallback" in body, (
            "Recent expense must also appear under all-time fallback"
        )

    def test_only_from_date_provided_fallback(self, auth_client, app):
        """If only from_date is provided (no to_date), the route falls back to all-time."""
        client, user_id = auth_client
        old = (date.today() - timedelta(days=400)).strftime("%Y-%m-%d")
        _insert_expense(app, user_id, 10.00, "Food", old, "Only from date test")

        response = client.get("/dashboard?from_date=2025-01-01")
        body = response.data.decode()
        assert response.status_code == 200, "Partial date params must not cause a 500"
        assert "Only from date test" in body, (
            "With only from_date, fallback to all-time means old expense is visible"
        )
        assert "Showing:" not in body, "No Showing label without both date params"

    def test_only_to_date_provided_fallback(self, auth_client, app):
        """If only to_date is provided (no from_date), the route falls back to all-time."""
        client, user_id = auth_client
        old = (date.today() - timedelta(days=400)).strftime("%Y-%m-%d")
        _insert_expense(app, user_id, 15.00, "Bills", old, "Only to date test")

        response = client.get("/dashboard?to_date=2025-12-31")
        body = response.data.decode()
        assert response.status_code == 200, "Only to_date must not cause a 500"
        assert "Only to date test" in body, (
            "With only to_date provided, all-time fallback means the old expense is visible"
        )
        assert "Showing:" not in body, "No Showing label without both date params"

    @pytest.mark.parametrize("from_date,to_date", [
        ("2025-13-01", "2025-12-31"),   # month 13 is invalid
        ("2025-00-01", "2025-12-31"),   # month 0 is invalid
        ("2025-02-30", "2025-12-31"),   # Feb 30 doesn't exist
        ("2025-01-01", "2025-13-01"),   # invalid to_date month
        ("not-a-date", "also-not"),     # both completely invalid
        ("", ""),                        # both empty strings
    ])
    def test_various_invalid_date_inputs_do_not_cause_500(self, auth_client, app, from_date, to_date):
        """Parametrized: a range of invalid date strings all return 200, not 500."""
        client, _ = auth_client
        response = client.get(f"/dashboard?from_date={from_date}&to_date={to_date}")
        assert response.status_code == 200, (
            f"Invalid dates from_date={from_date!r}, to_date={to_date!r} must return 200"
        )
        body = response.data.decode()
        assert "Showing:" not in body, (
            f"'Showing:' must not appear for invalid dates ({from_date!r}, {to_date!r})"
        )


# ---------------------------------------------------------------------------
# Active label format ("Showing: DD Mon YYYY – DD Mon YYYY")
# ---------------------------------------------------------------------------

class TestActiveFilterLabel:
    def test_active_label_format_for_this_month(self, auth_client, app):
        """For this_month preset, Showing label starts with the first day of the month."""
        client, user_id = auth_client
        today = date.today()
        first = date(today.year, today.month, 1)
        expected_from = first.strftime("%d %b %Y")  # e.g. "01 May 2026"
        expected_to = today.strftime("%d %b %Y")

        _insert_expense(app, user_id, 1.00, "Food", today.strftime("%Y-%m-%d"), "x")
        response = client.get("/dashboard?preset=this_month")
        body = response.data.decode()
        assert expected_from in body, f"'Showing:' label must contain '{expected_from}'"
        assert expected_to in body, f"'Showing:' label must contain '{expected_to}'"

    def test_active_label_format_for_custom_range(self, auth_client, app):
        """For a custom range, the Showing label shows both dates in DD Mon YYYY format."""
        client, user_id = auth_client
        _insert_expense(app, user_id, 5.00, "Food", "2025-03-15", "March")

        response = client.get("/dashboard?from_date=2025-03-01&to_date=2025-03-31")
        body = response.data.decode()
        assert "01 Mar 2025" in body, "from_date must render as '01 Mar 2025'"
        assert "31 Mar 2025" in body, "to_date must render as '31 Mar 2025'"

    def test_clear_link_points_to_unfiltered_dashboard(self, auth_client, app):
        """The Clear link removes all filter params, returning to plain /dashboard."""
        client, user_id = auth_client
        _insert_expense(app, user_id, 5.00, "Food", "2025-03-15", "March")

        response = client.get("/dashboard?from_date=2025-03-01&to_date=2025-03-31")
        body = response.data.decode()
        # The Clear link must lead to /dashboard without query params
        # Checking that href="/dashboard" appears near the Clear text
        clear_idx = body.find("Clear")
        assert clear_idx != -1, "'Clear' link must be present when filter is active"
        # Look for the anchor surrounding the Clear text
        snippet = body[max(0, clear_idx - 200): clear_idx + 10]
        assert 'href="/dashboard"' in snippet or "filter-clear" in snippet, (
            "Clear link must reference /dashboard without filter params"
        )


# ---------------------------------------------------------------------------
# Preset isolation — only one is-active at a time
# ---------------------------------------------------------------------------

class TestPresetIsolation:
    @pytest.mark.parametrize("preset,expected_active,should_not_be_active", [
        (
            "this_month",
            "This month",
            ["Last 3 months", "Last 6 months"],
        ),
        (
            "last_3_months",
            "Last 3 months",
            ["This month", "Last 6 months"],
        ),
        (
            "last_6_months",
            "Last 6 months",
            ["This month", "Last 3 months"],
        ),
    ])
    def test_only_selected_preset_is_active(
        self, auth_client, app, preset, expected_active, should_not_be_active
    ):
        """Only the selected preset link carries is-active; all others do not."""
        client, _ = auth_client
        response = client.get(f"/dashboard?preset={preset}")
        body = response.data.decode()

        def has_active_class_near(link_text, window=150):
            idx = body.find(link_text)
            if idx == -1:
                return False
            snippet = body[max(0, idx - window): idx]
            return "is-active" in snippet

        assert has_active_class_near(expected_active), (
            f"'{expected_active}' must have is-active when preset={preset}"
        )
        for inactive_text in should_not_be_active:
            assert not has_active_class_near(inactive_text), (
                f"'{inactive_text}' must NOT have is-active when preset={preset}"
            )

    def test_no_preset_all_time_is_active(self, auth_client, app):
        """With no preset param, only 'All time' carries is-active."""
        client, _ = auth_client
        response = client.get("/dashboard")
        body = response.data.decode()

        all_time_idx = body.rfind("All time")
        snippet = body[max(0, all_time_idx - 200): all_time_idx]
        assert "is-active" in snippet, "'All time' must be is-active when no preset is provided"

        for link_text in ["This month", "Last 3 months", "Last 6 months"]:
            idx = body.find(link_text)
            if idx != -1:
                near = body[max(0, idx - 150): idx]
                assert "is-active" not in near, (
                    f"'{link_text}' must NOT have is-active when no preset is selected"
                )


# ---------------------------------------------------------------------------
# Empty state — no expenses
# ---------------------------------------------------------------------------

class TestEmptyState:
    def test_dashboard_no_expenses_returns_200(self, auth_client, app):
        """Dashboard with no expenses at all should return 200 without errors."""
        client, _ = auth_client
        response = client.get("/dashboard")
        assert response.status_code == 200, "Empty dashboard must return 200"

    def test_this_month_no_expenses_in_range_returns_200(self, auth_client, app):
        """this_month filter with no matching expenses returns 200, not an error."""
        client, user_id = auth_client
        old = (date.today() - timedelta(days=400)).strftime("%Y-%m-%d")
        _insert_expense(app, user_id, 10.00, "Food", old, "Very old")

        response = client.get("/dashboard?preset=this_month")
        assert response.status_code == 200, (
            "No expenses in this_month range must still return 200"
        )
        body = response.data.decode()
        # Total spent should be 0 (or equivalent)
        assert "0.00" in body, "Total spent must be 0.00 when no expenses in filtered range"

    def test_custom_range_no_matching_expenses_returns_200(self, auth_client, app):
        """Custom range with no matching expenses returns 200 and shows zero totals."""
        client, user_id = auth_client
        _insert_expense(app, user_id, 50.00, "Bills", "2020-01-01", "Ancient bill")

        response = client.get("/dashboard?from_date=2030-01-01&to_date=2030-12-31")
        assert response.status_code == 200, "No expenses in future custom range must return 200"
        body = response.data.decode()
        assert "0.00" in body, "Total spent must be 0.00 when no expenses match the filter"
        # The expense from 2020 must not appear
        assert "Ancient bill" not in body, "Out-of-range expense must not appear"


# ---------------------------------------------------------------------------
# Template structure sanity
# ---------------------------------------------------------------------------

class TestTemplateStructure:
    def test_dashboard_extends_base(self, auth_client, app):
        """Dashboard response should include landmarks from base.html (nav, etc.)."""
        client, _ = auth_client
        response = client.get("/dashboard")
        body = response.data.decode()
        # base.html renders the page title; also check for Spendly branding
        assert "Spendly" in body, "Dashboard must include Spendly branding from base.html"

    def test_filter_bar_preset_links_present(self, auth_client, app):
        """All four preset link labels must appear in the filter bar."""
        client, _ = auth_client
        response = client.get("/dashboard")
        body = response.data.decode()
        for label in ["This month", "Last 3 months", "Last 6 months", "All time"]:
            assert label in body, f"Preset label '{label}' must be present in the filter bar"

    def test_custom_date_form_present(self, auth_client, app):
        """The custom date range form with from_date and to_date inputs must be present."""
        client, _ = auth_client
        response = client.get("/dashboard")
        body = response.data.decode()
        assert 'name="from_date"' in body, "Custom range form must include a from_date input"
        assert 'name="to_date"' in body, "Custom range form must include a to_date input"
        assert 'type="date"' in body, "Date inputs must use type=date"

    def test_stat_cards_present(self, auth_client, app):
        """All three stat cards (Total Spent, Total Expenses, Top Category) must render."""
        client, _ = auth_client
        response = client.get("/dashboard")
        body = response.data.decode()
        assert "Total Spent" in body
        assert "Total Expenses" in body
        assert "Top Category" in body

    def test_dashboard_page_title(self, auth_client, app):
        """Page title must identify the Dashboard."""
        client, _ = auth_client
        response = client.get("/dashboard")
        body = response.data.decode()
        assert "Dashboard" in body, "Page must contain 'Dashboard' in its content/title"
