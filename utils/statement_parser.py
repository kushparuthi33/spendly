import json
import os

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


class ParseError(Exception):
    pass


def parse_statement(csv_text: str) -> list:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY is not set. Please set it before using the import feature."
        )

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
            valid.append(
                {
                    "date": date,
                    "description": description[:255],
                    "amount": round(amount, 2),
                    "category": row["category"],
                }
            )
        except (KeyError, ValueError, TypeError, AssertionError):
            continue

    return valid
