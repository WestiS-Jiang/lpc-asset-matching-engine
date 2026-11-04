import unittest

import main
import scanner


class CatalogModeTests(unittest.TestCase):
    def test_scan_uses_committed_catalog_when_definitions_are_missing(self) -> None:
        result = scanner.scan_sheet_definitions()
        self.assertTrue(result["summary"]["catalog_mode"])
        self.assertGreater(result["summary"]["total_items"], 0)
        self.assertIn("body", result["manifest"])

    def test_generator_preview_route_reports_missing_optional_assets(self) -> None:
        from fastapi.testclient import TestClient

        response = TestClient(main.app).get("/generator/index.html")
        self.assertEqual(503, response.status_code)
        self.assertIn("Install LPC assets", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
