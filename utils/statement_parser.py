import csv
import io
import json
import os
from datetime import datetime

import anthropic

SYSTEM_PROMPT = (
    "You are a bank statement parser. Given raw CSV text from a bank statement, "
    "extract every debit/expense transaction and return ONLY a JSON array. "
    "No prose, no markdown fences, no explanation — just the raw JSON array.\n\n"
    "Each element must be exactly:\n"
    '{"date": "YYYY-MM-DD", "description": "...", "amount": <positive float>, '
    '"category": "<one of: Food, Transport, Bills, Health, Entertainment, Shopping, Other>"}\n\n'
    "Rules:\n"
    "- Skip credit entries, balance rows, opening/closing balance rows, and header rows\n"
    "- Use positive amounts only (debit/expense transactions)\n"
    "- Map categories to exactly the 7 allowed values\n"
    "- If the date format is ambiguous, prefer DD/MM/YYYY (common in Indian banks)\n"
    "- If no valid expense transactions are found, return an empty array []"
)

ALLOWED_CATEGORIES = {
    "Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"
}

# Keywords for rule-based categorisation (checked in order; first match wins)
_CATEGORY_KEYWORDS = [
    ("Food", [
        "zomato", "swiggy", "restaurant", "cafe", "food", "pizza", "burger",
        "dhaba", "haldiram", "mcdonald", "kfc", "dominos", "dunkin", "starbucks",
        "kitchen", "grocery", "grocer", "bigbasket", "blinkit", "zepto",
        "instamart", "dmart", "bakery", "canteen", "snacks", "tiffin",
    ]),
    ("Transport", [
        "uber", "ola", "rapido", "metro", "irctc", "railway", "redbus",
        "bus", "auto", "taxi", "cab", "petrol", "fuel", "parking",
        "fastag", "toll", "indigo", "spicejet", "airindia", "airasia",
        "makemytrip", "goibibo", "yatra",
    ]),
    ("Bills", [
        "electricity", "water bill", "jio", "airtel", "vodafone", "vi-",
        "bsnl", "broadband", "wifi", "internet", "recharge", "dth",
        "tata sky", "dish tv", "sun direct", "bescom", "msedcl", "tneb",
        "insurance", "lic ", "premium", "municipality", "gas bill",
    ]),
    ("Health", [
        "pharmacy", "medical", "hospital", "clinic", "doctor", "apollo",
        "1mg", "netmeds", "practo", "lab", "diagnostic", "health",
        "fitness", "gym", "medplus", "physio",
    ]),
    ("Entertainment", [
        "netflix", "amazon prime", "hotstar", "disney", "spotify",
        "youtube premium", "zee5", "sonyliv", "bookmyshow", "pvr", "inox",
        "gaming", "steam", "playstation", "xbox",
    ]),
    ("Shopping", [
        "amazon", "flipkart", "myntra", "ajio", "nykaa", "meesho",
        "snapdeal", "shoppers stop", "lifestyle store", "westside",
        "h&m", "zara", "max fashion", "pantaloons",
    ]),
]

_DATE_FORMATS = [
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%d/%m/%y", "%d-%m-%y", "%d.%m.%y",
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
    "%d %b %Y", "%d-%b-%Y", "%d/%b/%Y", "%d.%b.%Y",
    "%d %B %Y", "%d-%B-%Y",
]


class ParseError(Exception):
    pass


# ------------------------------------------------------------------ #
# Claude-based parser                                                  #
# ------------------------------------------------------------------ #

def parse_statement(csv_text: str) -> list:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": csv_text}],
        )
        raw = response.content[0].text.strip()
        rows = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ParseError(f"Claude returned invalid JSON: {e}")
    except IndexError:
        raise ParseError("Claude returned an empty response.")
    except anthropic.APIError as e:
        raise ParseError(f"Claude API error: {e}")

    if not isinstance(rows, list):
        raise ParseError("Claude returned an unexpected response format.")

    return _validate_rows(rows)


# ------------------------------------------------------------------ #
# Rule-based parser (no API key needed)                               #
# ------------------------------------------------------------------ #

def parse_statement_rules(csv_text: str) -> list:
    reader = csv.reader(io.StringIO(csv_text))
    all_rows = [r for r in reader if any(cell.strip() for cell in r)]

    if not all_rows:
        raise ParseError("The CSV file appears to be empty.")

    # Detect the header row
    header_idx, headers = _find_header(all_rows)
    if header_idx is None:
        raise ParseError(
            "Could not find a header row. Make sure your CSV includes "
            "column names like Date, Narration/Description, and Debit/Amount."
        )

    # Map columns
    date_col   = _find_col(headers, ["date", "txn date", "transaction date", "value date", "posting date"])
    desc_col   = _find_col(headers, ["narration", "description", "particulars", "remarks", "details", "reference", "beneficiary"])
    amount_col = _find_col(headers, ["debit", "debit amount", "withdrawal", "withdrawal amt", "dr amount", "dr"])
    if amount_col is None:
        amount_col = _find_col(headers, ["amount", "transaction amount", "txn amount"])
    drcr_col   = _find_col(headers, ["dr/cr", "cr/dr", "type", "txn type", "transaction type", "debit/credit"])

    if date_col is None or desc_col is None or amount_col is None:
        missing = [name for name, col in [("date", date_col), ("description", desc_col), ("amount", amount_col)] if col is None]
        raise ParseError(
            f"Could not detect column(s): {', '.join(missing)}. "
            "Ensure your CSV has Date, Description/Narration, and Debit/Amount columns."
        )

    expenses = []
    for row in all_rows[header_idx + 1:]:
        if len(row) <= max(date_col, desc_col, amount_col):
            continue

        # Skip credit rows
        if drcr_col is not None and drcr_col < len(row):
            marker = row[drcr_col].strip().upper()
            if marker in {"CR", "C", "CREDIT"}:
                continue

        # Parse amount
        raw_amount = row[amount_col].strip().replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
        if not raw_amount:
            continue
        try:
            amount = float(raw_amount)
        except ValueError:
            continue
        if amount <= 0:
            continue

        # Parse date
        parsed_date = _parse_date(row[date_col].strip())
        if not parsed_date:
            continue

        description = row[desc_col].strip()
        if not description:
            continue

        expenses.append({
            "date":        parsed_date,
            "description": description[:255],
            "amount":      round(amount, 2),
            "category":    _categorize(description),
        })

    return expenses


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _find_header(rows):
    for i, row in enumerate(rows):
        lower = [c.lower().strip() for c in row]
        has_date = any("date" in h for h in lower)
        has_desc = any(k in h for h in lower for k in
                       ["narration", "description", "particulars", "remarks", "details"])
        if has_date and has_desc:
            return i, lower
    # Fallback: treat first row as header
    return 0, [c.lower().strip() for c in rows[0]]


def _find_col(headers, keywords):
    for kw in keywords:
        for i, h in enumerate(headers):
            if kw in h:
                return i
    return None


def _parse_date(raw: str) -> str:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _categorize(description: str) -> str:
    desc_lower = description.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(kw in desc_lower for kw in keywords):
            return category
    return "Other"


def _validate_rows(rows: list) -> list:
    valid = []
    for row in rows:
        try:
            amount = float(row["amount"])
            assert amount > 0
            assert row.get("category") in ALLOWED_CATEGORIES
            date = str(row.get("date", "")).strip()
            assert date
            description = str(row.get("description", "")).strip()
            assert description
            valid.append({
                "date":        date,
                "description": description[:255],
                "amount":      round(amount, 2),
                "category":    row["category"],
            })
        except (KeyError, ValueError, TypeError, AssertionError):
            continue
    return valid
