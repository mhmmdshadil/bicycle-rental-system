import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as app_module


class DashboardStatsTests(unittest.TestCase):
    def test_get_homepage_stats_uses_database_counts(self):
        def fake_query(sql, params=None, fetch="all"):
            if "COUNT(DISTINCT type)" in sql:
                return {
                    "total_stations": 5,
                    "total_bikes": 16,
                    "available_bikes": 11,
                    "total_types": 3,
                }
            return None

        app_module.query = fake_query

        stats = app_module.get_homepage_stats()

        self.assertEqual(stats, {
            "stations": 5,
            "bicycles": 16,
            "types": 3,
            "available": 11,
        })

    def test_assign_student_display_ids_uses_sequential_numbers(self):
        students = [
            {"student_id": 15, "name": "A"},
            {"student_id": 3, "name": "B"},
            {"student_id": 22, "name": "C"},
        ]

        result = app_module.assign_student_display_ids(students)

        self.assertEqual([s["display_student_id"] for s in result], [1, 2, 3])
        self.assertEqual([s["student_id"] for s in result], [15, 3, 22])


if __name__ == "__main__":
    unittest.main()
