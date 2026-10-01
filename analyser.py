# -*- coding: utf-8 -*-
"""
MySQL Slow Query Log Parser & Composite Index Advisor
Author: Eng. MHD. Shadi AL-Hasan <mhd.shadi.alhasan@gmail.com>
Phone: +963934005922
Copyright (c) 2026 MHD. Shadi AL-Hasan
"""

import re
import argparse
from pathlib import Path
from collections import defaultdict

class SlowQueryAnalyser:
    def __init__(self, log_path: Path):
        self.log_path = log_path

    def analyze(self):
        print(f"[*] Analyzing slow query log: {self.log_path}")
        content = self.log_path.read_text(encoding="utf-8", errors="ignore")
        
        query_time_pattern = re.compile(r"# Query_time: ([0-9.]+)\s+Lock_time: ([0-9.]+)\s+Rows_sent: (\d+)\s+Rows_examined: (\d+)")
        
        blocks = content.split("# Time:")
        print(f"[*] Parsed {len(blocks)} log blocks.")
        
        slow_queries = []
        for b in blocks:
            match = query_time_pattern.search(b)
            if match:
                q_time = float(match.group(1))
                examined = int(match.group(4))
                # Extract SQL statement
                lines = [l.strip() for l in b.splitlines() if not l.startswith("#") and l.strip()]
                sql = " ".join(lines)
                slow_queries.append({"time": q_time, "rows_examined": examined, "sql": sql[:100]})

        slow_queries.sort(key=lambda x: x["time"], reverse=True)
        print("\n=== TOP SLOWEST QUERIES ===")
        for idx, q in enumerate(slow_queries[:5], 1):
            print(f"[{idx}] Time: {q['time']}s | Examined: {q['rows_examined']} rows")
            print(f"    SQL: {q['sql']}...")
            print("    [ADVICE] Examine WHERE conditions and consider adding composite INDEX.")

def main():
    parser = argparse.ArgumentParser(description="Parse MySQL slow query logs.")
    parser.add_argument("--log", "-l", required=True, help="Path to slow query log")
    args = parser.parse_args()

    analyser = SlowQueryAnalyser(Path(args.log))
    analyser.analyze()

if __name__ == "__main__":
    main()
