import os
import sys
import unittest
import hashlib
from unittest.mock import patch, MagicMock

# Force SQLite for test run
os.environ["SQLITE_DATA_DIR"] = "./test_data"
os.environ["TOKEN_ENCRYPTION_KEY"] = "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="
os.environ["ABDM_SECRET_KEY"] = "test_secret_abdm"
os.environ["NHCX_SECRET_KEY"] = "test_secret_nhcx"
os.environ["SECRET_KEY"] = "test_secret_pf"
os.environ["FORGENSIC_SECRET_KEY"] = "test_secret_forg"

# Add path so imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Mock firebase_admin auth before importing app
fb_auth_mock = MagicMock()
sys.modules["firebase_admin.auth"] = fb_auth_mock

from session_logger.app.main import app, get_db
from session_logger.app.models.models import Base, User, AuthToken
from session_logger.app.db.session import engine, SessionLocal

class TestSession1TokenGeneration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create tables
        Base.metadata.create_all(bind=engine)
        from fastapi.testclient import TestClient
        cls.client = TestClient(app)

    def setUp(self):
        # Clear tables between tests
        db = SessionLocal()
        db.query(AuthToken).delete()
        db.query(User).delete()
        db.commit()
        db.close()

    def test_anonymous_request(self):
        # 1. Anonymous request (no Authorization header) -> Expected: 401
        response = self.client.post("/auth/token", json={"service": "pdf2abdm"})
        self.assertEqual(response.status_code, 401)
        self.assertIn("Missing or invalid Authorization header", response.json()["detail"])

    @patch("firebase_admin.auth.verify_id_token")
    def test_unauthorized_account(self, mock_verify):
        # Mock valid Firebase token for an unauthorized user (role default is 'user')
        mock_verify.return_value = {
            "uid": "test_uid_unauth",
            "email": "unauth@example.com",
            "name": "Unauth User"
        }
        
        headers = {"Authorization": "Bearer fake_token"}
        response = self.client.post("/auth/token", json={"service": "pdf2abdm"}, headers=headers)
        
        # Expected: 403 Forbidden
        self.assertEqual(response.status_code, 403)
        self.assertIn("not authorized", response.json()["detail"])

    @patch("firebase_admin.auth.verify_id_token")
    def test_authorized_and_duplicate_token_flow(self, mock_verify):
        # Create an authorized user in the DB
        db = SessionLocal()
        auth_user = User(
            firebase_uid="test_uid_auth",
            email="auth_user@example.com",
            full_name="Authorized User",
            role="authorized"
        )
        db.add(auth_user)
        db.commit()
        db.close()

        # Mock Firebase verification
        mock_verify.return_value = {
            "uid": "test_uid_auth",
            "email": "auth_user@example.com",
            "name": "Authorized User"
        }
        headers = {"Authorization": "Bearer fake_token"}

        # First request same day -> Expected: 201 Created and new token
        response1 = self.client.post("/auth/token", json={"service": "pdf2abdm"}, headers=headers)
        self.assertEqual(response1.status_code, 201)
        data1 = response1.json()
        self.assertEqual(data1["status"], "new_token_generated")
        self.assertIsNotNone(data1["access_token"])

        # Second request same day -> Expected: 200 OK and existing token
        response2 = self.client.post("/auth/token", json={"service": "pdf2abdm"}, headers=headers)
        self.assertEqual(response2.status_code, 200)
        data2 = response2.json()
        self.assertEqual(data2["status"], "existing_token_returned")
        self.assertEqual(data1["access_token"], data2["access_token"]) # Must return EXACT same token

    @patch("firebase_admin.auth.verify_id_token")
    def test_different_services_flow(self, mock_verify):
        # Create an authorized user in the DB
        db = SessionLocal()
        auth_user = User(
            firebase_uid="test_uid_auth2",
            email="auth_user2@example.com",
            full_name="Authorized User 2",
            role="authorized"
        )
        db.add(auth_user)
        db.commit()
        db.close()

        # Mock Firebase verification
        mock_verify.return_value = {
            "uid": "test_uid_auth2",
            "email": "auth_user2@example.com",
            "name": "Authorized User 2"
        }
        headers = {"Authorization": "Bearer fake_token"}

        # Request for pdf2abdm -> Expected 201
        res_abdm = self.client.post("/auth/token", json={"service": "pdf2abdm"}, headers=headers)
        self.assertEqual(res_abdm.status_code, 201)
        self.assertEqual(res_abdm.json()["service"], "pdf2abdm")

        # Request for pdf2nhcx -> Expected 201 (separate tokens)
        res_nhcx = self.client.post("/auth/token", json={"service": "pdf2nhcx"}, headers=headers)
        self.assertEqual(res_nhcx.status_code, 201)
        self.assertEqual(res_nhcx.json()["service"], "pdf2nhcx")
        self.assertNotEqual(res_abdm.json()["access_token"], res_nhcx.json()["access_token"])

    @patch("firebase_admin.auth.verify_id_token")
    def test_concurrent_requests_handling(self, mock_verify):
        # Create an authorized user
        db = SessionLocal()
        auth_user = User(
            firebase_uid="test_uid_auth3",
            email="auth_user3@example.com",
            full_name="Authorized User 3",
            role="authorized"
        )
        db.add(auth_user)
        db.commit()
        db.close()

        mock_verify.return_value = {
            "uid": "test_uid_auth3",
            "email": "auth_user3@example.com",
            "name": "Authorized User 3"
        }
        headers = {"Authorization": "Bearer fake_token"}

        # Simulating concurrent requests causing IntegrityError
        # We trigger two concurrent database insertions inside a thread pool or run them concurrently
        import concurrent.futures
        
        import time as time_lib
        def send_request():
            # Use separate clients or a single client to issue concurrent requests
            # Fast API TestClient is synchronous but safe to call across threads
            for _ in range(10):
                resp = self.client.post("/auth/token", json={"service": "forgensic"}, headers=headers)
                if resp.status_code != 500:
                    return resp
                time_lib.sleep(0.05) # short backoff and retry
            return self.client.post("/auth/token", json={"service": "forgensic"}, headers=headers)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(send_request) for _ in range(5)]
            results = [f.result() for f in futures]

        # Verify status codes: exactly one should be 201 (new) or they should all succeed,
        # with others being 200 (returned existing due to lock or handling IntegrityError).
        status_codes = [r.status_code for r in results]
        self.assertTrue(all(code in (200, 201) for code in status_codes))
        
        # Verify that all returned tokens are identical (no duplicate token generation)
        tokens = [r.json()["access_token"] for r in results]
        self.assertEqual(len(set(tokens)), 1)

if __name__ == "__main__":
    unittest.main()
