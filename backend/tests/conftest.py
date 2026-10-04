import os
import pytest
from unittest.mock import patch

os.environ["REQUIRE_HMAC_SIGNATURE"] = "false"
os.environ["POSTGRES_URL"] = "postgresql://test:test@localhost:5432/test"

import fastapi.testclient

original_request = fastapi.testclient.TestClient.request

def patched_request(self, method, url, **kwargs):
    headers = kwargs.get("headers") or {}
    headers.setdefault("X-Tenant-ID", "tenant-a")
    headers.setdefault("X-User-ID", "user-1")
    kwargs["headers"] = headers
    return original_request(self, method, url, **kwargs)

fastapi.testclient.TestClient.request = patched_request

