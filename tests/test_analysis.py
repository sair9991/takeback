"""
tests/test_analysis.py - Unit tests for clean importable analysis module.
"""

import unittest
from unittest.mock import patch

from analysis import (
    get_batch_model_stats,
    get_batch_postgres_data,
    get_model_stats,
    get_person_postgres_data,
    get_postgres_data,
    train_model,
)


class TestAnalysisModule(unittest.TestCase):

    def test_train_model(self):
        """Test calling train_model function."""
        fake_response = {
            "status": "completed",
            "player_id": "testplayer",
            "val_accuracy": 0.654,
            "val_loss": 1.721,
            "model_stats": {"val_loss": 1.721, "val_accuracy": 0.654},
        }

        with patch("analysis.model_analysis._http_call", return_value=fake_response) as mock_call:
            result = train_model("testplayer", force=True)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["val_loss"], 1.721)
            mock_call.assert_called_once()
            args, kwargs = mock_call.call_args
            self.assertIn("/api/clones/testplayer/train?force=true", args[0])
            self.assertEqual(kwargs["method"], "POST")

    def test_get_model_stats_ready(self):
        """Test retrieving stats for an already trained model."""
        fake_stats = {
            "player_id": "testplayer",
            "val_accuracy": 0.62,
            "val_loss": 1.85,
            "weights_path": "models/testplayer.pt",
            "model_name": "clone",
            "access_count": 12,
        }

        with patch("analysis.model_analysis._http_call", return_value=fake_stats):
            res = get_model_stats("testplayer")
            self.assertEqual(res["person"], "testplayer")
            self.assertEqual(res["loss"], 1.85)
            self.assertEqual(res["accuracy"], 0.62)
            self.assertEqual(res["status"], "ready")

    def test_get_batch_model_stats(self):
        """Test batch pulling stats across multiple people."""
        fake_stats = {
            "stuffyness": {"val_accuracy": 0.65, "val_loss": 1.70, "access_count": 2},
            "kovinar": {"val_accuracy": 0.61, "val_loss": 1.80, "access_count": 5},
        }

        def mock_http(url, method="GET", data=None, timeout=30):
            for name, stats in fake_stats.items():
                if name in url:
                    return stats
            raise RuntimeError("Not found")

        with patch("analysis.model_analysis._http_call", side_effect=mock_http):
            batch = get_batch_model_stats(["stuffyness", "kovinar"])
            self.assertEqual(len(batch), 2)
            self.assertEqual(batch[0]["person"], "stuffyness")
            self.assertEqual(batch[0]["loss"], 1.70)
            self.assertEqual(batch[0]["accuracy"], 0.65)
            self.assertEqual(batch[1]["person"], "kovinar")
            self.assertEqual(batch[1]["loss"], 1.80)
            self.assertEqual(batch[1]["accuracy"], 0.61)

    def test_get_postgres_data(self):
        """Test querying PostgreSQL data."""
        fake_rows = [
            {"player_id": "p1", "val_accuracy": 0.70, "val_loss": 1.50},
            {"player_id": "p2", "val_accuracy": 0.60, "val_loss": 1.90},
        ]

        with patch("analysis.model_analysis.get_postgres_connection") as mock_conn:
            mock_cursor = mock_conn.return_value.cursor.return_value.__enter__.return_value
            mock_cursor.fetchall.return_value = fake_rows
            data = get_postgres_data("models")
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]["player_id"], "p1")

    def test_get_batch_postgres_data(self):
        """Test batch pulling PostgreSQL records for multiple people."""
        fake_models = [
            {"player_id": "stuffyness", "val_accuracy": 0.65, "val_loss": 1.70},
            {"player_id": "kovinar", "val_accuracy": 0.61, "val_loss": 1.80},
        ]
        fake_counts = [
            {"player_id": "stuffyness", "game_count": 42},
            {"player_id": "kovinar", "game_count": 18},
        ]

        def mock_query(sql, params=None, database_url=None):
            if "v_model_stats" in sql:
                return fake_models
            if "COUNT(*)" in sql:
                return fake_counts
            return []

        with patch("analysis.model_analysis.get_postgres_data", side_effect=mock_query):
            res = get_batch_postgres_data(["stuffyness", "kovinar"])
            self.assertIn("stuffyness", res)
            self.assertEqual(res["stuffyness"]["total_games"], 42)
            self.assertEqual(res["stuffyness"]["model"]["val_loss"], 1.70)
            self.assertIn("kovinar", res)
            self.assertEqual(res["kovinar"]["total_games"], 18)


if __name__ == "__main__":
    unittest.main()
