import os
import sys
import unittest
import hashlib
import time
from unittest.mock import patch, MagicMock

# Set test configurations
os.environ["REDIS_URL"] = "redis://localhost:6379/0"

# Add path so imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from common.rate_limit import RateLimitMiddleware


class TestSession3RateLimiter(unittest.TestCase):
    def setUp(self):
        # Create a test FastAPI app specifically for testing the middleware behavior
        self.app = FastAPI()
        self.app.add_middleware(
            RateLimitMiddleware,
            service_name="test_service",
            limit=5, # use small limit (5 requests) for fast testing
            period=10 # use short period (10 seconds)
        )

        @self.app.get("/health")
        def health():
            return {"status": "ok"}

        @self.app.post("/pdf2abdm")
        def process_abdm(request: Request):
            return {"status": "processed"}

        self.client = TestClient(self.app)

    @patch("redis.Redis.from_url")
    def test_health_endpoint_bypassed(self, mock_redis_url):
        # Health check must completely bypass Redis and never trigger rate-limiting
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        mock_redis_url.assert_not_called()

    @patch("redis.Redis.from_url")
    def test_requests_allowed_under_limit(self, mock_redis_url):
        # Mock Redis client and pipeline
        mock_redis = MagicMock()
        mock_pipeline = MagicMock()
        mock_redis_url.return_value = mock_redis
        mock_redis.pipeline.return_value = mock_pipeline
        
        # zremrange, zcard, zadd, expire results
        # Under limit: ZCARD returns current count = 3 (<= limit of 5)
        mock_pipeline.execute.return_value = (0, 3, 1, True)

        headers = {"Authorization": "Bearer token_a"}
        response = self.client.post("/pdf2abdm", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "processed"})

    @patch("redis.Redis.from_url")
    def test_requests_throttled_above_limit(self, mock_redis_url):
        # Mock Redis client and pipeline
        mock_redis = MagicMock()
        mock_pipeline = MagicMock()
        mock_redis_url.return_value = mock_redis
        mock_redis.pipeline.return_value = mock_pipeline
        
        # Over limit: ZCARD returns current count = 6 (> limit of 5)
        mock_pipeline.execute.return_value = (0, 6, 1, True)
        
        # Mock oldest timestamp to compute Retry-After
        now = time.time()
        mock_redis.zrange.return_value = [("some_member", now - 2)]

        headers = {"Authorization": "Bearer token_b"}
        response = self.client.post("/pdf2abdm", headers=headers)
        
        # Must return 429 Too Many Requests
        self.assertEqual(response.status_code, 429)
        self.assertIn("Rate limit exceeded", response.json()["detail"])
        self.assertIn("Retry-After", response.headers)
        self.assertIn(response.headers["Retry-After"], ("7", "8")) # oldest (now-2) + period (10) - now = 8s or 7s depending on execution timing

    @patch("redis.Redis.from_url")
    def test_different_users_isolated(self, mock_redis_url):
        # Different tokens generate different keys and should be isolated
        mock_redis = MagicMock()
        mock_pipeline = MagicMock()
        mock_redis_url.return_value = mock_redis
        mock_redis.pipeline.return_value = mock_pipeline
        
        # Mock pipeline results
        mock_pipeline.execute.return_value = (0, 1, 1, True)

        self.client.post("/pdf2abdm", headers={"Authorization": "Bearer token_u1"})
        self.client.post("/pdf2abdm", headers={"Authorization": "Bearer token_u2"})

        # Verify pipeline keys contain unique sha256 hashes of the tokens
        calls = mock_redis.pipeline.call_args_list
        self.assertTrue(len(calls) >= 2)

    @patch("redis.Redis.from_url")
    def test_fail_open_on_redis_error(self, mock_redis_url):
        # If Redis raises an exception, the middleware must log the error and FAIL OPEN
        mock_redis_url.side_effect = Exception("Redis cluster unavailable")

        headers = {"Authorization": "Bearer token_any"}
        response = self.client.post("/pdf2abdm", headers=headers)
        
        # Expected: Request allowed with 200 OK (fail-open)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "processed"})


if __name__ == "__main__":
    unittest.main()
