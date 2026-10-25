"""
tests/test_revised_gemma.py - Unit tests for revised Gemma commentary and search features.
"""

import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVISED_BACKEND = ROOT / "revised" / "backend"
if str(REVISED_BACKEND) not in sys.path:
    sys.path.insert(0, str(REVISED_BACKEND))

# Mock container dependencies for host environment if not installed
import types
for mod_name in ["psycopg", "psycopg.rows", "psycopg_pool", "chess", "chess.engine", "chess.svg", "chess.pgn", "httpx"]:
    if mod_name not in sys.modules:
        m = types.ModuleType(mod_name)
        m.__spec__ = MagicMock()
        m.__path__ = []
        sys.modules[mod_name] = m

sys.modules["psycopg.rows"].dict_row = MagicMock()
sys.modules["psycopg_pool"].ConnectionPool = MagicMock()

from app.services.commentary_service import (
    _clean_and_parse_json,
    generate_structured_commentary,
)
from app.services import embedding_service


class TestRevisedGemma(unittest.TestCase):

    def test_clean_and_parse_json_markdown_blocks(self):
        """Verify robust JSON extraction from markdown code fences."""
        raw = """Here is the chess analysis:
```json
{
  "narrative": "White opened aggressively with the Italian Game.",
  "tags": ["Italian Game", "Tactical Blunder"],
  "commentary": [
    {
      "ply": 14,
      "phase": "Critical Moment",
      "headline": "Decisive Blunder",
      "text": "Black hung a rook with 14...Qe7.",
      "isPivotal": true,
      "pivotalLabel": "Blunder"
    }
  ]
}
```
Hope this helps!"""
        parsed = _clean_and_parse_json(raw)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["narrative"], "White opened aggressively with the Italian Game.")
        self.assertEqual(len(parsed["commentary"]), 1)
        self.assertEqual(parsed["commentary"][0]["ply"], 14)
        self.assertTrue(parsed["commentary"][0]["isPivotal"])

    def test_clean_and_parse_json_trailing_commas(self):
        """Verify JSON parsing when LLM outputs trailing commas."""
        raw = """{
  "narrative": "Sharp tactical match.",
  "tags": ["Sicilian", "Defense",],
  "commentary": [
    {"ply": 2, "phase": "Opening", "headline": "Early Contest", "text": "Fighting for center.",},
  ],
}"""
        parsed = _clean_and_parse_json(raw)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["narrative"], "Sharp tactical match.")

    def test_structured_commentary_multi_moment_generation(self):
        """Verify multi-moment structured commentary fallback generates opening, blunder, and ending."""
        game = {
            "player_id": "hikaru",
            "opponent_username": "magnus",
            "player_color": "white",
            "result": "win",
        }
        moves = [
            {"ply": 1, "side": "white", "move": "e4"},
            {"ply": 2, "side": "black", "move": "e5"},
            {"ply": 3, "side": "white", "move": "Nf3"},
            {"ply": 4, "side": "black", "move": "Nc6"},
            {"ply": 5, "side": "white", "move": "Bc4"},
            {"ply": 6, "side": "black", "move": "Nf6"},
            {"ply": 7, "side": "white", "move": "Ng5"},
            {"ply": 8, "side": "black", "move": "d5"},
            {"ply": 9, "side": "white", "move": "exd5"},
            {"ply": 10, "side": "black", "move": "Na5"},
            {"ply": 11, "side": "white", "move": "Bb5+"},
            {"ply": 12, "side": "black", "move": "c6"},
            {"ply": 13, "side": "white", "move": "dxc6"},
            {"ply": 14, "side": "black", "move": "bxc6"},
        ]
        # Odds swinging sharply on ply 7 (move 7)
        odds = [50.0, 50.0, 52.0, 51.0, 53.0, 52.0, 75.0, 72.0, 74.0, 73.0, 80.0, 78.0, 85.0, 83.0]

        with patch("app.services.commentary_service._query_local_gemma", return_value=""):
            commentary, narrative = generate_structured_commentary(game, moves, odds)

            self.assertGreater(len(commentary), 1)
            # Check plies are sorted
            plies = [c["ply"] for c in commentary]
            self.assertEqual(plies, sorted(plies))
            # Verify pivotal swing was flagged
            pivotal_items = [c for c in commentary if c.get("isPivotal")]
            self.assertGreater(len(pivotal_items), 0)
            self.assertTrue(narrative["narrative"])
            self.assertGreater(len(narrative["tags"]), 0)

    def test_structured_commentary_with_valid_gemma_json(self):
        """Verify LLM commentary output is properly parsed, validated, and normalized."""
        game = {
            "player_id": "hikaru",
            "opponent_username": "magnus",
            "player_color": "white",
            "result": "win",
        }
        moves = [
            {"ply": 1, "side": "white", "move": "e4"},
            {"ply": 2, "side": "black", "move": "c5"},
            {"ply": 3, "side": "white", "move": "Nf3"},
            {"ply": 4, "side": "black", "move": "d6"},
        ]
        odds = [50.0, 52.0, 54.0, 53.0]

        fake_gemma_reply = """```json
{
  "narrative": "A Sicilian Defense where White maintained sharp central control.",
  "tags": ["Sicilian Defense", "Open Sicilian", "Tactical Pressure"],
  "commentary": [
    {
      "ply": 2,
      "phase": "Opening",
      "headline": "Sicilian Defense Accepted",
      "text": "Black challenges White's central dominance with the asymmetric c5 thrust.",
      "isPivotal": false,
      "pivotalLabel": "Opening"
    },
    {
      "ply": 4,
      "phase": "Middlegame",
      "headline": "Sharp Kingside Prep",
      "text": "White coordinates minor pieces while Black solidifies d6.",
      "isPivotal": true,
      "pivotalLabel": "Turning Point"
    }
  ]
}
```"""
        with patch("app.services.commentary_service._query_local_gemma", return_value=fake_gemma_reply):
            commentary, narrative = generate_structured_commentary(game, moves, odds)
            self.assertEqual(len(commentary), 2)
            self.assertEqual(commentary[0]["ply"], 2)
            self.assertEqual(commentary[1]["ply"], 4)
            self.assertTrue(commentary[1]["isPivotal"])
            self.assertIn("moment-4", commentary[1]["pivotalId"])
            self.assertEqual(narrative["narrative"], "A Sicilian Defense where White maintained sharp central control.")
            self.assertIn("Sicilian Defense", narrative["tags"])


if __name__ == "__main__":
    unittest.main()
