"""Security regressions; no real user data required."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "llm_todo_server.py"
spec = importlib.util.spec_from_file_location("llm_todo_security", SCRIPT)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class SecurityTests(unittest.TestCase):
    def test_empty_token_denies_api_access(self):
        handler = server.Handler.__new__(server.Handler)
        handler.headers = {}
        replies = []
        handler.send_response = lambda code: replies.append(code)
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        handler.wfile = type("Sink", (), {"write": lambda self, data: None})()
        with patch.object(server, "AUTH_TOKEN", ""):
            self.assertFalse(handler.authorized("/api/tasks"))
        self.assertEqual(replies, [401])

    def test_private_runtime_data_not_tracked(self):
        import subprocess
        result = subprocess.run(
            ["git", "ls-files", "--", "data/"],
            cwd=SCRIPT.parent.parent, capture_output=True, text=True, check=True
        )
        self.assertEqual(result.stdout.strip(), "")

    def test_server_requires_admin_token(self):
        env = os.environ.copy()
        env.pop("LLM_TODO_TOKEN", None)
        p = subprocess.run([sys.executable, str(SCRIPT)], env=env,
                           capture_output=True, text=True, timeout=8)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("Refusing to start", p.stderr)

    def test_no_known_default_signing_secret(self):
        with patch.object(server, "AUTH_TOKEN", ""), patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                server.jwt_secret()

    def test_expiration_and_legacy_jwt_rejection(self):
        agent = {"id": "agent-1", "name": "Example"}
        state = {"agents": [agent], "sessions": {}}
        with patch.object(server, "AUTH_TOKEN", "test-secret-not-for-production"):
            with patch.dict(os.environ, {"LLM_TODO_JWT_SECRET": "unit-test-secret-only"}):
                with patch.object(server, "load_agents", return_value=state):
                    with patch.object(server, "save_agents", side_effect=lambda data: state.update(data)):
                        token = server.create_agent_session(agent)
                        body = json.loads(server.b64url_decode(token.split(".")[1]))
                        self.assertEqual(body["exp"] - body["iat"], 86400)
                        self.assertEqual(server.verify_agent_jwt(token), agent)
                        with patch.object(server.time, "time", return_value=body["exp"] + 1):
                            self.assertIsNone(server.verify_agent_jwt(token))
                        old = dict(body)
                        del old["exp"]
                        header = token.split(".")[0]
                        encoded = server.b64url_encode(json.dumps(old).encode())
                        message = f"{header}.{encoded}"
                        old_token = f"{message}.{server.sign_agent_jwt(message)}"
                        state["sessions"][old_token] = {"agentId": agent["id"]}
                        self.assertIsNone(server.verify_agent_jwt(old_token))


if __name__ == "__main__":
    unittest.main()
