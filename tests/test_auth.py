import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask, jsonify


API_SERVER = Path(__file__).resolve().parents[1] / "artifacts" / "api-server"
sys.path.insert(0, str(API_SERVER))

from auth import is_authorized_user, require_auth  # noqa: E402


class AllowlistTests(unittest.TestCase):
    def test_production_requires_verified_exact_email_match(self):
        with patch.dict(
            os.environ,
            {
                "NODE_ENV": "production",
                "SOP_ALLOWED_EMAILS": "Reviewer@Example.com, second@example.com",
            },
        ):
            self.assertTrue(
                is_authorized_user(
                    {"email": "reviewer@example.com", "email_verified": True}
                )
            )
            self.assertFalse(
                is_authorized_user(
                    {"email": "reviewer@example.com", "email_verified": False}
                )
            )
            self.assertFalse(
                is_authorized_user(
                    {"email": "other@example.com", "email_verified": True}
                )
            )

    def test_empty_allowlist_fails_closed_in_production(self):
        with patch.dict(
            os.environ,
            {"NODE_ENV": "production", "SOP_ALLOWED_EMAILS": ""},
        ):
            self.assertFalse(
                is_authorized_user(
                    {"email": "reviewer@example.com", "email_verified": True}
                )
            )

    def test_protected_route_returns_401_or_403_before_allowing_access(self):
        app = Flask(__name__)
        app.secret_key = "test-only"

        @app.get("/private")
        @require_auth
        def private():
            return jsonify({"ok": True})

        with patch.dict(
            os.environ,
            {
                "NODE_ENV": "production",
                "SOP_ALLOWED_EMAILS": "allowed@example.com",
                "ALLOW_DEV_AUTH_BYPASS": "true",
            },
        ):
            client = app.test_client()
            self.assertEqual(client.get("/private").status_code, 401)
            with client.session_transaction() as user_session:
                user_session["user"] = {
                    "email": "blocked@example.com",
                    "email_verified": True,
                }
            self.assertEqual(client.get("/private").status_code, 403)
            with client.session_transaction() as user_session:
                user_session["user"] = {
                    "email": "allowed@example.com",
                    "email_verified": True,
                }
            self.assertEqual(client.get("/private").status_code, 200)


if __name__ == "__main__":
    unittest.main()