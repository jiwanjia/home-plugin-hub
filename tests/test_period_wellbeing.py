import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp_plugins import period_tracker


class PeriodWellbeingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data_path = Path(self.temporary.name) / "period_data.json"
        self.data_path.write_text(
            json.dumps({"records": [], "current": None}),
            encoding="utf-8",
        )
        self.path_patch = patch.object(period_tracker, "DATA_FILE", str(self.data_path))
        self.path_patch.start()
        self.plugin = period_tracker.PeriodTrackerPlugin()

    def tearDown(self):
        self.path_patch.stop()
        self.temporary.cleanup()

    def read_data(self):
        return json.loads(self.data_path.read_text(encoding="utf-8"))

    def test_legacy_period_document_gains_empty_wellbeing_collections(self):
        data = period_tracker._load_data()

        self.assertEqual([], data["records"])
        self.assertIsNone(data["current"])
        self.assertEqual([], data["body_events"])
        self.assertEqual([], data["mood_events"])

    def test_body_toggle_records_one_start_and_end_interval(self):
        started = self.plugin.execute(action="body_toggle", event_type="headache")
        active = period_tracker._wellbeing_snapshot(self.read_data())
        ended = self.plugin.execute(action="body_toggle", event_type="headache")
        finished = period_tracker._wellbeing_snapshot(self.read_data())

        self.assertTrue(started.ok)
        self.assertTrue(active["body"]["headache"]["active"])
        self.assertTrue(ended.ok)
        self.assertFalse(finished["body"]["headache"]["active"])
        self.assertEqual(1, len(finished["body_events"]))
        event = finished["body_events"][0]
        self.assertTrue(event["start_at"])
        self.assertTrue(event["end_at"])

    def test_body_types_are_independent(self):
        self.plugin.execute(action="body_start", event_type="headache")
        self.plugin.execute(action="body_start", event_type="nausea")
        self.plugin.execute(action="body_end", event_type="headache")
        snapshot = period_tracker._wellbeing_snapshot(self.read_data())

        self.assertFalse(snapshot["body"]["headache"]["active"])
        self.assertTrue(snapshot["body"]["nausea"]["active"])

    def test_moods_are_instant_events_without_end_time(self):
        happy = self.plugin.execute(action="mood", event_type="happy")
        unhappy = self.plugin.execute(action="mood", event_type="unhappy")
        snapshot = period_tracker._wellbeing_snapshot(self.read_data())

        self.assertTrue(happy.ok)
        self.assertTrue(unhappy.ok)
        self.assertEqual(["unhappy", "happy"], [item["kind"] for item in snapshot["mood_events"]])
        self.assertTrue(all("occurred_at" in item for item in snapshot["mood_events"]))
        self.assertTrue(all("end_at" not in item for item in snapshot["mood_events"]))

    def test_invalid_body_or_mood_kind_fails_without_write(self):
        before = self.data_path.read_text(encoding="utf-8")
        body = self.plugin.execute(action="body_start", event_type="dizzy")
        mood = self.plugin.execute(action="mood", event_type="angry")

        self.assertFalse(body.ok)
        self.assertFalse(mood.ok)
        self.assertEqual(before, self.data_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
