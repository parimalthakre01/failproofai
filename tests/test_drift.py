import os
import tempfile
import unittest


class DriftApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("DRIFT_DB")
        self.old_spool = os.environ.get("FAILPROOF_SPOOL")
        os.environ["DRIFT_DB"] = os.path.join(self.temp.name, "drift.sqlite3")
        os.environ["FAILPROOF_SPOOL"] = os.path.join(self.temp.name, "spool")
        # Import after per-test paths are selected. The app lifespan configures SDK.
        from fastapi.testclient import TestClient
        from server import app
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        if self.old_db is None:
            os.environ.pop("DRIFT_DB", None)
        else:
            os.environ["DRIFT_DB"] = self.old_db
        if self.old_spool is None:
            os.environ.pop("FAILPROOF_SPOOL", None)
        else:
            os.environ["FAILPROOF_SPOOL"] = self.old_spool
        self.temp.cleanup()

    def test_faulty_profile_creates_alert_and_withholds_answer(self):
        response = self.client.post("/api/evaluations", json={
            "domain": "finance", "variant": "faulty", "mode": "demo",
            "question": "Explain DSCR.", "threshold": 0.5,
        })
        self.assertEqual(response.status_code, 200)
        run = response.json()
        self.assertEqual(run["status"], "drift_detected")
        self.assertTrue(run["drift_detected"])
        self.assertIsNone(run["released_answer"])
        self.assertEqual(run["alert"]["kind"], "DomainDriftDetected")

    def test_benchmark_covers_all_domains_and_off_domain_failures(self):
        response = self.client.post("/api/benchmarks", json={"mode": "demo", "threshold": 0.5})
        self.assertEqual(response.status_code, 200)
        batch = response.json()
        self.assertEqual(batch["status"], "completed")
        self.assertEqual(batch["summary"]["cases"], 6)
        self.assertEqual(batch["summary"]["correct"], 6)
        self.assertEqual(batch["summary"]["alerts"], 3)


if __name__ == "__main__":
    unittest.main()
