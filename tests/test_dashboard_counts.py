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
    def test_station_id_rendered_in_admin_stations_template(self):
        with app_module.app.test_request_context("/admin/stations"):
            html = app_module.render_template(
                "admin_stations.html",
                stations=[{
                    "station_id": 4,
                    "name": "Hostel Hub",
                    "location": "Behind Block B",
                    "capacity": 10,
                    "available": 6,
                    "rented": 3,
                    "reserved": 1,
                    "maintenance": 0,
                    "total": 10,
                }],
                bikes=[{
                    "bicycle_id": 12,
                    "display_bicycle_id": 1,
                    "model": "Trek FX 2",
                    "type": "standard",
                    "station_id": 4,
                    "station_name": "Hostel Hub",
                    "added_at": None,
                    "status": "available",
                }],
            )
            self.assertIn("ID #4", html)
            self.assertIn("Station ID: #4", html)

    def test_station_id_rendered_in_student_bikes_template(self):
        with app_module.app.test_request_context("/student/bikes"):
            app_module.session["student_name"] = "Alice"
            html = app_module.render_template(
                "student_bikes.html",
                stations=[{
                    "station_id": 7,
                    "name": "North Gate",
                    "location": "Near Main Gate",
                    "capacity": 8,
                    "available": 5,
                }],
                bikes=[{
                    "bicycle_id": 20,
                    "model": "Giant Escape 3",
                    "type": "mountain",
                    "station_id": 7,
                    "station_name": "North Gate",
                }],
                station_filter="all",
                type_filter="all",
            )
            self.assertIn("ID #7", html)
            self.assertIn("Station #7", html)


if __name__ == "__main__":
    unittest.main()
