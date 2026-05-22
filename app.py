import os
from datetime import datetime
from flask import Flask, render_template, request, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from database.db import (get_db, init_db, seed_db, create_user, get_user_by_email,
    get_user_by_id, update_user_name, update_user_password,
    get_expenses_by_user, get_monthly_total, get_category_totals, get_expense_count,
    bulk_insert_expenses)

def _format_member_since(created_at):
    return datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").strftime("%B %-d, %Y")


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-spendly")

with app.app_context():
    init_db()
    seed_db()


EXPENSE_CATEGORIES = ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("landing"))
    if request.method == "GET":
        return render_template("register.html")

    name             = request.form.get("name",             "").strip()
    email            = request.form.get("email",            "").strip()
    password         = request.form.get("password",         "")
    confirm_password = request.form.get("confirm_password", "")

    if not name:
        return render_template("register.html", error="Name is required.")
    if not email:
        return render_template("register.html", error="Email is required.", name=name)
    if len(password) < 8:
        return render_template("register.html",
                               error="Password must be at least 8 characters.",
                               name=name, email=email)
    if password != confirm_password:
        return render_template("register.html",
                               error="Passwords do not match.",
                               name=name, email=email)
    if get_user_by_email(email):
        return render_template("register.html",
                               error="An account with that email already exists.",
                               name=name, email=email)

    create_user(name, email, generate_password_hash(password))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("landing"))
    if request.method == "GET":
        return render_template("login.html")

    email    = request.form.get("email",    "").strip()
    password = request.form.get("password", "")

    if not email or not password:
        return render_template("login.html", error="Invalid email or password.", email=email)

    user = get_user_by_email(email)
    if not user or not check_password_hash(user["password_hash"], password):
        return render_template("login.html", error="Invalid email or password.", email=email)

    session["user_id"]   = user["id"]
    session["user_name"] = user["name"]
    return redirect(url_for("landing"))


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    uid = session["user_id"]
    now = datetime.now()
    hour = now.hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 18:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    expenses = get_expenses_by_user(uid)
    monthly_total, monthly_count = get_monthly_total(uid, now.year, now.month)
    category_totals = get_category_totals(uid)
    total_count = get_expense_count(uid)

    top_category = category_totals[0]["category"] if category_totals else "—"
    max_cat_total = category_totals[0]["total"] if category_totals else 1

    categories = [
        {
            "name": row["category"],
            "total": row["total"],
            "pct": round(row["total"] / max_cat_total * 100),
        }
        for row in category_totals
    ]

    return render_template(
        "dashboard.html",
        greeting=greeting,
        name=session["user_name"],
        expenses=expenses,
        monthly_total=monthly_total,
        monthly_count=monthly_count,
        total_count=total_count,
        top_category=top_category,
        categories=categories,
    )


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(request.referrer or url_for("landing"))


@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = get_user_by_id(session["user_id"])
    member_since = _format_member_since(user["created_at"])

    if request.method == "GET":
        return render_template("profile.html", user=user, member_since=member_since)

    action = request.form.get("action", "")

    if action == "update_name":
        name = request.form.get("name", "").strip()
        if not name:
            return render_template("profile.html", user=user, member_since=member_since,
                                   error_name="Name is required.")
        if len(name) > 100:
            return render_template("profile.html", user=user, member_since=member_since,
                                   error_name="Name must be 100 characters or fewer.", name_value=name)
        update_user_name(session["user_id"], name)
        session["user_name"] = name
        user = get_user_by_id(session["user_id"])
        return render_template("profile.html", user=user, member_since=member_since,
                               success_name="Name updated successfully.")

    if action == "change_password":
        current_pw = request.form.get("current_password", "")
        new_pw     = request.form.get("new_password", "")
        confirm_pw = request.form.get("confirm_password", "")
        if not check_password_hash(user["password_hash"], current_pw):
            return render_template("profile.html", user=user, member_since=member_since,
                                   error_password="Current password is incorrect.")
        if new_pw == current_pw:
            return render_template("profile.html", user=user, member_since=member_since,
                                   error_password="New password must be different from your current password.")
        if len(new_pw) < 8:
            return render_template("profile.html", user=user, member_since=member_since,
                                   error_password="New password must be at least 8 characters.")
        if new_pw != confirm_pw:
            return render_template("profile.html", user=user, member_since=member_since,
                                   error_password="New passwords do not match.")
        update_user_password(session["user_id"], generate_password_hash(new_pw))
        return render_template("profile.html", user=user, member_since=member_since,
                               success_password="Password changed successfully.")

    return redirect(url_for("profile"))


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if "user_id" not in session:
        return redirect(url_for("login"))
    from database.db import create_expense
    today = datetime.now().strftime("%Y-%m-%d")
    if request.method == "GET":
        return render_template(
            "expenses/add.html",
            categories=EXPENSE_CATEGORIES,
            today=today,
        )
    amount_raw  = request.form.get("amount", "").strip()
    category    = request.form.get("category", "").strip()
    date        = request.form.get("date", "").strip()
    description = request.form.get("description", "").strip()
    try:
        amount = float(amount_raw)
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return render_template(
            "expenses/add.html",
            categories=EXPENSE_CATEGORIES, today=today,
            error="Please enter a valid amount greater than 0.",
            amount_value=amount_raw, category_value=category,
            date_value=date, description_value=description,
        )
    if category not in EXPENSE_CATEGORIES:
        return render_template(
            "expenses/add.html",
            categories=EXPENSE_CATEGORIES, today=today,
            error="Please select a valid category.",
            amount_value=amount_raw, category_value=category,
            date_value=date, description_value=description,
        )
    if not date:
        return render_template(
            "expenses/add.html",
            categories=EXPENSE_CATEGORIES, today=today,
            error="Date is required.",
            amount_value=amount_raw, category_value=category,
            date_value=date, description_value=description,
        )
    create_expense(session["user_id"], amount, category, date, description)
    return redirect(url_for("dashboard"))


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    from database.db import get_expense_by_id, update_expense
    from flask import abort
    expense = get_expense_by_id(id)
    if expense is None:
        abort(404)
    if expense["user_id"] != session["user_id"]:
        abort(403)
    if request.method == "GET":
        return render_template(
            "expenses/edit.html",
            categories=EXPENSE_CATEGORIES,
            amount_value=expense["amount"],
            category_value=expense["category"],
            date_value=expense["date"],
            description_value=expense["description"] or "",
        )
    amount_raw  = request.form.get("amount", "").strip()
    category    = request.form.get("category", "").strip()
    date        = request.form.get("date", "").strip()
    description = request.form.get("description", "").strip()
    try:
        amount = float(amount_raw)
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return render_template(
            "expenses/edit.html",
            categories=EXPENSE_CATEGORIES,
            error="Please enter a valid amount greater than 0.",
            amount_value=amount_raw, category_value=category,
            date_value=date, description_value=description,
        )
    if category not in EXPENSE_CATEGORIES:
        return render_template(
            "expenses/edit.html",
            categories=EXPENSE_CATEGORIES,
            error="Please select a valid category.",
            amount_value=amount_raw, category_value=category,
            date_value=date, description_value=description,
        )
    if not date:
        return render_template(
            "expenses/edit.html",
            categories=EXPENSE_CATEGORIES,
            error="Date is required.",
            amount_value=amount_raw, category_value=category,
            date_value=date, description_value=description,
        )
    update_expense(id, amount, category, date, description)
    return redirect(url_for("dashboard"))


@app.route("/expenses/<int:id>/delete", methods=["GET", "POST"])
def delete_expense(id):
    from database.db import get_expense_by_id, remove_expense
    from flask import abort
    if request.method == "GET":
        return redirect(url_for("dashboard"))
    if "user_id" not in session:
        return redirect(url_for("login"))
    expense = get_expense_by_id(id)
    if expense is None:
        abort(404)
    if expense["user_id"] != session["user_id"]:
        abort(403)
    remove_expense(id)
    return redirect(url_for("dashboard"))


MAX_UPLOAD_BYTES = 1 * 1024 * 1024  # 1 MB


@app.route("/import", methods=["GET", "POST"])
def import_statement():
    if "user_id" not in session:
        return redirect(url_for("login"))
    if request.method == "GET":
        return render_template("import/upload.html")

    f = request.files.get("file")
    if not f or not f.filename:
        return render_template("import/upload.html", error="Please select a CSV file.")
    if not f.filename.lower().endswith(".csv"):
        return render_template("import/upload.html", error="Only CSV files are accepted.")
    raw = f.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        return render_template("import/upload.html", error="File is too large (max 1 MB).")
    csv_text = raw.decode("utf-8", errors="replace")
    if not csv_text.strip():
        return render_template("import/upload.html", error="The uploaded file is empty.")

    from utils.statement_parser import parse_statement, parse_statement_rules, ParseError
    try:
        if os.environ.get("ANTHROPIC_API_KEY"):
            rows = parse_statement(csv_text)
        else:
            rows = parse_statement_rules(csv_text)
    except (ParseError, EnvironmentError) as e:
        return render_template("import/upload.html", error=str(e))

    if not rows:
        return render_template("import/upload.html",
                               error="No expense transactions were found in the file.")

    session["import_rows"] = rows
    return redirect(url_for("import_preview"))


@app.route("/import/preview")
def import_preview():
    if "user_id" not in session:
        return redirect(url_for("login"))
    rows = session.get("import_rows")
    if not rows:
        return redirect(url_for("import_statement"))
    return render_template("import/preview.html",
                           rows=rows,
                           categories=EXPENSE_CATEGORIES)


@app.route("/import/confirm", methods=["POST"])
def import_confirm():
    if "user_id" not in session:
        return redirect(url_for("login"))
    rows = session.get("import_rows", [])
    selected_indices = request.form.getlist("row_index")
    category_overrides = request.form.getlist("category")

    to_insert = []
    for idx_str, cat in zip(selected_indices, category_overrides):
        try:
            row = rows[int(idx_str)]
        except (ValueError, IndexError):
            continue
        if cat not in EXPENSE_CATEGORIES:
            cat = row["category"]
        to_insert.append({
            "user_id":     session["user_id"],
            "amount":      row["amount"],
            "category":    cat,
            "date":        row["date"],
            "description": row["description"],
        })

    if to_insert:
        bulk_insert_expenses(to_insert)

    session.pop("import_rows", None)
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
