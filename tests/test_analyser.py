# -*- coding: utf-8 -*-
"""
Automated Test Suite for MySQL Slow Query Log Parser & Advisor
Tests synthetic log parsing, thresholds, exports, and advice engine.
"""

import os
import csv
import json
import tempfile
import unittest
from pathlib import Path
from analyser import SlowQueryAnalyser, load_env

SYNTHETIC_SLOW_LOG = """
# Time: 2026-10-01T10:15:30.123456Z
# User@Host: app_user[app_user] @ db_client.internal [10.0.1.25]  Id:  1042
# Query_time: 8.542100  Lock_time: 0.000120 Rows_sent: 5  Rows_examined: 540000
SET timestamp=1790850930;
SELECT u.id, u.email, o.total_amount
FROM users u
JOIN orders o ON u.id = o.user_id
WHERE u.status = 'active' AND o.created_at >= '2026-01-01'
ORDER BY o.total_amount DESC;

# Time: 2026-10-01T10:16:02.789123Z
# User@Host: report_svc[report_svc] @ localhost []  Id:  1088
# Query_time: 2.150000  Lock_time: 0.000050 Rows_sent: 0  Rows_examined: 85000
SET timestamp=1790850962;
SELECT id, transaction_code FROM transactions
WHERE account_id = 998822 AND status = 'pending'
ORDER BY created_at ASC;

# Time: 2026-10-01T10:16:45.000000Z
# User@Host: monitoring[monitoring] @ localhost []  Id:  1099
# Query_time: 0.050000  Lock_time: 0.000010 Rows_sent: 1  Rows_examined: 1
SELECT 1;
"""

class TestSlowQueryAnalyser(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.temp_dir.name) / "synthetic_slow.log"
        self.log_file.write_text(SYNTHETIC_SLOW_LOG, encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_synthetic_logs_extracts_all_queries(self):
        analyser = SlowQueryAnalyser(log_path=self.log_file, min_time=0.0, min_rows=0)
        queries = analyser.analyze()

        self.assertEqual(len(queries), 3)
        # Verify descending order by query time
        self.assertGreaterEqual(queries[0]["time"], queries[1]["time"])
        self.assertGreaterEqual(queries[1]["time"], queries[2]["time"])

        top = queries[0]
        self.assertAlmostEqual(top["time"], 8.5421)
        self.assertAlmostEqual(top["lock_time"], 0.000120)
        self.assertEqual(top["rows_sent"], 5)
        self.assertEqual(top["rows_examined"], 540000)
        self.assertIn("app_user", top["user_host"])
        self.assertIn("SELECT u.id, u.email", top["sql"])

    def test_filter_by_min_query_time_threshold(self):
        # Filtering queries with min_time >= 1.0s should eliminate the 0.05s query
        analyser = SlowQueryAnalyser(log_path=self.log_file, min_time=1.0)
        queries = analyser.analyze()

        self.assertEqual(len(queries), 2)
        for q in queries:
            self.assertGreaterEqual(q["time"], 1.0)

    def test_filter_by_min_rows_examined_threshold(self):
        # Filtering queries with min_rows >= 100,000 should keep only the top query
        analyser = SlowQueryAnalyser(log_path=self.log_file, min_rows=100000)
        queries = analyser.analyze()

        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0]["rows_examined"], 540000)

    def test_recommendation_and_index_advice(self):
        analyser = SlowQueryAnalyser()
        
        # Test full table scan advice
        advice_scan = analyser.generate_advice(
            "SELECT * FROM large_table WHERE non_indexed_col = 1",
            rows_examined=50000,
            rows_sent=2,
            query_time=4.5
        )
        self.assertIn("Full table scan detected", advice_scan)

        # Test composite index advice for WHERE + ORDER BY
        advice_composite = analyser.generate_advice(
            "SELECT id FROM events WHERE status = 'live' ORDER BY start_time DESC",
            rows_examined=200,
            rows_sent=10,
            query_time=0.8
        )
        self.assertIn("composite INDEX", advice_composite)

        # Test JOIN advice
        advice_join = analyser.generate_advice(
            "SELECT a.name, b.title FROM authors a JOIN books b ON a.id = b.author_id",
            rows_examined=500,
            rows_sent=100,
            query_time=1.2
        )
        self.assertIn("foreign keys", advice_join)

    def test_export_to_json(self):
        analyser = SlowQueryAnalyser(log_path=self.log_file, min_time=0.5)
        queries = analyser.analyze()

        json_out = Path(self.temp_dir.name) / "reports" / "slow.json"
        saved_path = SlowQueryAnalyser.export_json(queries, json_out)

        self.assertTrue(saved_path.exists())
        with saved_path.open(encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["rows_examined"], 540000)
        self.assertIn("advice", data[0])

    def test_export_to_csv(self):
        analyser = SlowQueryAnalyser(log_path=self.log_file, min_time=0.0)
        queries = analyser.analyze()

        csv_out = Path(self.temp_dir.name) / "reports" / "slow.csv"
        saved_path = SlowQueryAnalyser.export_csv(queries, csv_out)

        self.assertTrue(saved_path.exists())
        with saved_path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["rows_examined"], "540000")
        self.assertEqual(rows[0]["rows_sent"], "5")
        self.assertIn("advice", rows[0])

    def test_missing_log_file_raises_error(self):
        analyser = SlowQueryAnalyser(log_path=Path("non_existent_file.log"))
        with self.assertRaises(FileNotFoundError):
            analyser.analyze()

    def test_empty_log_content_returns_empty_list(self):
        analyser = SlowQueryAnalyser()
        queries = analyser.parse_content("")
        self.assertEqual(queries, [])

    def test_env_loader(self):
        env_file = Path(self.temp_dir.name) / ".env.test"
        env_file.write_text("MIN_QUERY_TIME=3.5\nTOP_N=15\n# Comment\n", encoding="utf-8")

        loaded = load_env(str(env_file))
        self.assertEqual(loaded.get("MIN_QUERY_TIME"), "3.5")
        self.assertEqual(loaded.get("TOP_N"), "15")


if __name__ == "__main__":
    unittest.main()
