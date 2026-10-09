import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.server.auth.provider import AccessToken
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from auth import Auth0TokenVerifier
import mcp_server


class FakeVerifier:
    async def verify_token(self, token):
        owners = {"token-a": "auth0|user-a", "token-b": "auth0|user-b"}
        owner = owners.get(token)
        if not owner:
            return None
        return AccessToken(
            token=token,
            client_id="test-client",
            scopes=["simulation:use"],
            expires_at=int(time.time()) + 300,
            resource="https://mcp.example.com",
            subject=owner,
        )


class SigningKey:
    def __init__(self, key):
        self.key = key


class StaticJwks:
    def __init__(self, key):
        self.key = key

    def get_signing_key_from_jwt(self, token):
        return SigningKey(self.key)


class RemoteMcpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = str(Path(self.tmp.name) / "remote.sqlite3")
        self.environment = patch.dict(
            os.environ,
            {
                "DATABASE_URL": self.database,
                "OPS_PUBLIC_URL": "https://mcp.example.com/mcp",
                "AUTH0_ISSUER_URL": "https://example.auth0.com/",
                "AUTH0_AUDIENCE": "https://mcp.example.com",
                "OPS_REQUIRED_SCOPE": "simulation:use",
            },
            clear=False,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        verifier = patch.object(mcp_server, "Auth0TokenVerifier", return_value=FakeVerifier())
        verifier.start()
        self.addCleanup(verifier.stop)
        self.client = TestClient(mcp_server.create_app(), base_url="https://mcp.example.com")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.case_id = json.loads((ROOT / "data/patient_1.json").read_text())["case_id"]
        self.request_id = 0

    def post(self, method, params=None, token="token-a"):
        self.request_id += 1
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        body = {"jsonrpc": "2.0", "id": self.request_id, "method": method}
        if params is not None:
            body["params"] = params
        return self.client.post("/mcp", headers=headers, json=body)

    def call(self, name, arguments, token="token-a"):
        response = self.post("tools/call", {"name": name, "arguments": arguments}, token)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["result"]

    def test_health_authentication_initialization_and_discovery(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        unauthorized = self.post("tools/list", token="invalid")
        self.assertEqual(unauthorized.status_code, 401)
        self.assertIn("resource_metadata", unauthorized.headers.get("www-authenticate", ""))
        initialized = self.post(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        self.assertEqual(initialized.status_code, 200, initialized.text)
        discovered = self.post("tools/list", {})
        self.assertEqual(discovered.status_code, 200, discovered.text)
        tools = discovered.json()["result"]["tools"]
        self.assertEqual([tool["name"] for tool in tools], [tool["name"] for tool in mcp_server.TOOLS])
        self.assertEqual([tool["inputSchema"] for tool in tools], [tool["inputSchema"] for tool in mcp_server.TOOLS])

    def test_valid_invalid_persistence_isolation_images_and_feedback_gates(self):
        invalid = self.call("load_case", {"case_id": self.case_id, "owner_id": "model-value"})
        self.assertTrue(invalid["isError"])
        loaded = self.call("load_case", {"case_id": self.case_id})
        sid = loaded["structuredContent"]["session_id"]

        persisted = self.call("get_patient_fact", {"session_id": sid, "field": "age"})
        self.assertEqual(persisted["structuredContent"]["value"], 65)
        foreign = self.call("get_patient_fact", {"session_id": sid, "field": "age"}, "token-b")
        self.assertTrue(foreign["isError"])
        self.assertEqual(foreign["structuredContent"]["error"]["code"], "SESSION_NOT_FOUND")

        image = self.call("get_linked_image", {"session_id": sid, "test": "None", "eye": "both"})
        self.assertTrue(any(item["type"] == "image" for item in image["content"]))
        self.assertNotIn("data", image["structuredContent"]["images"][0])

        locked = self.call("evaluate_case", {"session_id": sid})
        self.assertEqual(locked["structuredContent"]["error"]["code"], "FEEDBACK_LOCKED")
        self.call("end_case", {"session_id": sid})
        not_requested = self.call("evaluate_case", {"session_id": sid})
        self.assertEqual(not_requested["structuredContent"]["error"]["code"], "FEEDBACK_NOT_REQUESTED")
        self.call(
            "record_interaction",
            {"session_id": sid, "interaction": {"actor": "user", "text": "give me feedback"}},
        )
        ready = self.call("evaluate_case", {"session_id": sid})
        self.assertEqual(ready["structuredContent"]["status"], "feedback_context_ready")
        self.assertFalse(ready["structuredContent"]["feedback_generated"])


class Auth0VerifierTests(unittest.TestCase):
    def setUp(self):
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public = self.private.public_key()
        self.issuer = "https://example.auth0.com/"
        self.audience = "https://mcp.example.com"

    def token(self, **overrides):
        now = int(time.time())
        claims = {
            "iss": self.issuer,
            "aud": self.audience,
            "iat": now,
            "exp": now + 300,
            "sub": "auth0|user-a",
            "scope": "simulation:use",
        }
        claims.update(overrides)
        return jwt.encode(claims, self.private, algorithm="RS256", headers={"kid": "test"})

    def verifier(self):
        verifier = Auth0TokenVerifier(self.issuer, self.audience, "simulation:use")
        verifier.jwks = StaticJwks(self.public)
        return verifier

    def test_signature_issuer_audience_expiry_scope_and_subject(self):
        accepted = asyncio.run(self.verifier().verify_token(self.token()))
        self.assertEqual(accepted.subject, "auth0|user-a")
        self.assertIsNone(asyncio.run(self.verifier().verify_token(self.token(aud="wrong"))))
        self.assertIsNone(asyncio.run(self.verifier().verify_token(self.token(iss="https://wrong.example/"))))
        self.assertIsNone(asyncio.run(self.verifier().verify_token(self.token(exp=int(time.time()) - 1))))
        self.assertIsNone(asyncio.run(self.verifier().verify_token(self.token(scope="other"))))
        self.assertIsNone(asyncio.run(self.verifier().verify_token(self.token(sub=""))))
        wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = int(time.time())
        forged = jwt.encode(
            {"iss": self.issuer, "aud": self.audience, "iat": now, "exp": now + 300,
             "sub": "auth0|attacker", "scope": "simulation:use"},
            wrong_key,
            algorithm="RS256",
            headers={"kid": "test"},
        )
        self.assertIsNone(asyncio.run(self.verifier().verify_token(forged)))


if __name__ == "__main__":
    unittest.main()
