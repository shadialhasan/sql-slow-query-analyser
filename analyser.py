# -*- coding: utf-8 -*-
"""
MySQL Slow Query Log Parser & Composite Index Advisor
Author: Eng. MHD. Shadi AL-Hasan <mhd.shadi.alhasan@gmail.com>
Phone: +963934005922
Copyright (c) 2026 MHD. Shadi AL-Hasan
"""

import os
import re
import csv
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional

def load_env(env_path: Optional[str] = None) -> Dict[str, str]:
    """Lightweight .env loader without third-party dependencies."""
    target_path = Path(env_path) if env_path else Path(".env")
    env_vars = {}
    if not target_path.exists():
        return env_vars

    with target_path.open(encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip()
            if (val.startswith('"') and val.endsWith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            env_vars[key] = val
            if key not in os.environ:
                os.environ[key] = val
    return env_vars


class SlowQueryAnalyser:
    def __init__(
        self,
        log_path: Optional[Path] = None,
        min_time: float = 0.0,
        min_rows: int = 0,
        top_n: int = 5
    ):
        self.log_path = log_path
        self.min_time = float(min_time)
        self.min_rows = int(min_rows)
        self.top_n = int(top_n)

    def generate_advice(self, sql: str, rows_examined: int, rows_sent: int, query_time: float) -> str:
        """Heuristic recommendation engine for slow query optimization."""
        upper_sql = sql.upper()
        advice = []

        if rows_examined > 1000 and rows_sent > 0 and (rows_examined / max(rows_sent, 1)) > 50:
            advice.append(
                f"Full table scan detected ({rows_examined} rows examined for {rows_sent} rows returned). "
                "Add selective index on filter predicate."
            )
        elif rows_examined > 5000 and rows_sent == 0:
            advice.append(
                f"Extensive scan ({rows_examined} rows examined) with 0 rows returned. "
                "Ensure indexing covers WHERE conditions."
            )

        if "JOIN" in upper_sql:
            advice.append("Examine JOIN ON predicates and verify foreign keys are indexed.")

        if "ORDER BY" in upper_sql and "WHERE" in upper_sql:
            advice.append("Consider composite INDEX covering WHERE filter and ORDER BY sorting columns.")
        elif "GROUP BY" in upper_sql:
            advice.append("Check GROUP BY columns for composite index coverage to avoid temporary filesort.")
        
        if not advice:
            advice.append("Examine WHERE conditions and consider adding composite INDEX.")

        return " | ".join(advice)

    def parse_content(self, content: str) -> List[Dict[str, Any]]:
        """Parses raw MySQL/MariaDB slow query log content into structured records."""
        query_time_pattern = re.compile(
            r"# Query_time:\s+([0-9.]+)\s+Lock_time:\s+([0-9.]+)\s+Rows_sent:\s+(\d+)\s+Rows_examined:\s+(\d+)"
        )
        user_host_pattern = re.compile(r"# User@Host:\s+([^\n]+)")
        timestamp_pattern = re.compile(r"(?:# Time:\s+([^\n]+)|SET timestamp=(\d+);)")

        # Segment log into query blocks
        raw_blocks = []
        current_block = []
        for line in content.splitlines():
            if line.startswith("# Time:"):
                if current_block and any("Query_time:" in l for l in current_block):
                    raw_blocks.append("\n".join(current_block))
                    current_block = []
            elif line.startswith("# User@Host:"):
                if current_block and any("Query_time:" in l for l in current_block):
                    raw_blocks.append("\n".join(current_block))
                    current_block = []
            current_block.append(line)
        if current_block and any("Query_time:" in l for l in current_block):
            raw_blocks.append("\n".join(current_block))

        slow_queries = []

        for b in raw_blocks:
            match = query_time_pattern.search(b)
            if not match:
                continue

            q_time = float(match.group(1))
            lock_time = float(match.group(2))
            rows_sent = int(match.group(3))
            rows_examined = int(match.group(4))

            # Apply threshold filtering
            if q_time < self.min_time or rows_examined < self.min_rows:
                continue

            # Extract user/host if present
            user_host_match = user_host_pattern.search(b)
            user_host = user_host_match.group(1).strip() if user_host_match else "unknown"

            # Extract timestamp if present
            time_match = timestamp_pattern.search(b)
            time_val = (time_match.group(1) or time_match.group(2)).strip() if time_match else ""

            # Extract clean SQL statement
            sql_lines = []
            for line in b.splitlines():
                l = line.strip()
                if not l:
                    continue
                if l.startswith("#"):
                    continue
                if l.upper().startswith("SET TIMESTAMP="):
                    continue
                sql_lines.append(l)

            sql = " ".join(sql_lines)
            if not sql:
                continue

            advice = self.generate_advice(sql, rows_examined, rows_sent, q_time)

            slow_queries.append({
                "time": q_time,
                "lock_time": lock_time,
                "rows_sent": rows_sent,
                "rows_examined": rows_examined,
                "user_host": user_host,
                "timestamp": time_val,
                "sql": sql,
                "sql_preview": sql[:120] + ("..." if len(sql) > 120 else ""),
                "advice": advice
            })

        slow_queries.sort(key=lambda x: x["time"], reverse=True)
        return slow_queries

    def analyze(self) -> List[Dict[str, Any]]:
        """Reads log from disk and parses offending slow queries."""
        if not self.log_path or not Path(self.log_path).exists():
            raise FileNotFoundError(f"Slow query log file not found: {self.log_path}")

        print(f"[*] Analyzing slow query log: {self.log_path}")
        print(f"[*] Filters applied: min_time >= {self.min_time}s, min_rows >= {self.min_rows}")
        content = Path(self.log_path).read_text(encoding="utf-8", errors="ignore")
        
        parsed = self.parse_content(content)
        print(f"[*] Found {len(parsed)} queries matching configured thresholds.")

        top_queries = parsed[:self.top_n]
        print(f"\n=== TOP {len(top_queries)} SLOWEST QUERIES ===")
        for idx, q in enumerate(top_queries, 1):
            print(f"[{idx}] Time: {q['time']}s | Lock: {q['lock_time']}s | Sent: {q['rows_sent']} | Examined: {q['rows_examined']} rows")
            print(f"    SQL: {q['sql_preview']}")
            print(f"    [ADVICE] {q['advice']}")

        return parsed

    @staticmethod
    def export_json(queries: List[Dict[str, Any]], output_path: Path | str) -> Path:
        """Export parsed slow queries to JSON."""
        dest = Path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="utf-8") as f:
            json.dump(queries, f, indent=2)
        return dest

    @staticmethod
    def export_csv(queries: List[Dict[str, Any]], output_path: Path | str) -> Path:
        """Export parsed slow queries to CSV."""
        dest = Path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "timestamp",
            "time",
            "lock_time",
            "rows_sent",
            "rows_examined",
            "user_host",
            "sql",
            "advice"
        ]
        with dest.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for q in queries:
                writer.writerow(q)
        return dest


def main():
    load_env()
    parser = argparse.ArgumentParser(
        description="High-performance MySQL / MariaDB Slow Query Log Analyzer & Index Advisor"
    )
    parser.add_argument("--log", "-l", default=os.getenv("SLOW_LOG_PATH"), help="Path to slow query log")
    parser.add_argument(
        "--min-time", "-t",
        type=float,
        default=float(os.getenv("MIN_QUERY_TIME", 0.0)),
        help="Minimum query execution time threshold in seconds (default: 0.0)"
    )
    parser.add_argument(
        "--min-rows", "-r",
        type=int,
        default=int(os.getenv("MIN_ROWS_EXAMINED", 0)),
        help="Minimum rows examined threshold (default: 0)"
    )
    parser.add_argument(
        "--top", "-n",
        type=int,
        default=int(os.getenv("TOP_N", 5)),
        help="Number of top slowest queries to display (default: 5)"
    )
    parser.add_argument("--export-json", help="Path to export results as JSON")
    parser.add_argument("--export-csv", help="Path to export results as CSV")
    parser.add_argument(
        "--format",
        choices=["table", "json", "csv"],
        default=os.getenv("EXPORT_FORMAT", "table"),
        help="Console output format (table, json, csv)"
    )

    args = parser.parse_args()

    if not args.log:
        parser.error("Log file path must be specified via --log / -l or SLOW_LOG_PATH in .env")

    analyser = SlowQueryAnalyser(
        log_path=Path(args.log),
        min_time=args.min_time,
        min_rows=args.min_rows,
        top_n=args.top
    )

    queries = analyser.analyze()

    if args.export_json:
        saved_json = SlowQueryAnalyser.export_json(queries, args.export_json)
        print(f"\n[+] Successfully exported JSON report to: {saved_json}")

    if args.export_csv:
        saved_csv = SlowQueryAnalyser.export_csv(queries, args.export_csv)
        print(f"[+] Successfully exported CSV report to: {saved_csv}")

    if args.format == "json" and not args.export_json:
        print("\n=== JSON OUTPUT ===")
        print(json.dumps(queries[:args.top], indent=2))
    elif args.format == "csv" and not args.export_csv:
        print("\n=== CSV OUTPUT ===")
        csv_path = Path("temp_output.csv")
        SlowQueryAnalyser.export_csv(queries[:args.top], csv_path)
        print(csv_path.read_text(encoding="utf-8"))
        csv_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
