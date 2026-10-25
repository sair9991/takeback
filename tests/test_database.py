"""
tests/test_database.py - Unit tests for SQLite database schema and backend operations.
"""

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backend.database import Database, parse_clock_string


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_chess.db"
        db = Database(db_path=db_path)
        yield db


def test_schema_initialization(temp_db):
    """Verify that all four required tables are created."""
    with temp_db.session() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        ).fetchall()
        table_names = [r["name"] for r in tables]

    assert "users" in table_names
    assert "games" in table_names
    assert "moves" in table_names
    assert "models" in table_names


def test_users_table_operations(temp_db):
    """Test user creation, update, and retrieval by player_id."""
    user = temp_db.create_or_get_user(
        user_id="hikaru",
        chess_com_username="Hikaru",
        lichess_username=None,
    )
    assert user["user_id"] == "hikaru"
    assert user["chess_com_username"] == "Hikaru"
    assert user["lichess_username"] is None

    # Update with lichess username
    updated = temp_db.create_or_get_user(
        user_id="hikaru",
        lichess_username="HikaruLichess",
    )
    assert updated["user_id"] == "hikaru"
    assert updated["chess_com_username"] == "Hikaru"
    assert updated["lichess_username"] == "HikaruLichess"

    fetched = temp_db.get_user("hikaru")
    assert fetched is not None
    assert fetched["user_id"] == "hikaru"


def test_games_table_operations(temp_db):
    """Test inserting games linked to player_id."""
    game_pk = temp_db.insert_game(
        player_id="stuffyness",
        src="chess.com",
        player_color="Black",
        opponent_color="White",
        player_elo=1813,
        opponent_elo=1850,
        opponent_username="Zzlatko",
        result="loss",
        game_id="137576275260",
        time_control="600",
        date="2025.04.20",
    )
    assert isinstance(game_pk, int)
    assert game_pk > 0

    # User should have been auto-registered
    user = temp_db.get_user("stuffyness")
    assert user is not None
    assert user["user_id"] == "stuffyness"

    # Fetch game by primary key
    game = temp_db.get_game_by_id(game_pk)
    assert game["player_id"] == "stuffyness"
    assert game["src"] == "chess.com"
    assert game["player_color"] == "black"
    assert game["opponent_color"] == "white"
    assert game["player_elo"] == 1813
    assert game["opponent_elo"] == 1850
    assert game["opponent_username"] == "Zzlatko"
    assert game["result"] == "loss"
    assert game["game_id"] == "137576275260"

    # Fetch games for player
    player_games = temp_db.get_games_by_player_id("stuffyness")
    assert len(player_games) == 1
    assert player_games[0]["id"] == game_pk


def test_moves_table_operations(temp_db):
    """Test moves table insertion and query by individual game id."""
    test_moves = [
        {"ply": 1, "side": "white", "move": "e4", "time_remaining": 598.8, "clock_str": "0:09:58.8"},
        {"ply": 2, "side": "black", "move": "c6", "time_remaining": 577.3, "clock_str": "0:09:37.3"},
        {"ply": 3, "side": "white", "move": "d4", "time_remaining": 597.2, "clock_str": "0:09:57.2"},
        {"ply": 4, "side": "black", "move": "d5", "time_remaining": 572.1, "clock_str": "0:09:32.1"},
    ]

    inserted_count = temp_db.insert_moves("game_test_123", test_moves)
    assert inserted_count == 4

    moves = temp_db.get_moves_by_game_id("game_test_123")
    assert len(moves) == 4
    assert moves[0]["move"] == "e4"
    assert moves[0]["side"] == "white"
    assert moves[0]["ply"] == 1
    assert moves[0]["time_remaining"] == 598.8
    assert moves[0]["clock_str"] == "0:09:58.8"

    assert moves[1]["move"] == "c6"
    assert moves[1]["side"] == "black"
    assert moves[1]["ply"] == 2


def test_models_table_operations(temp_db):
    """Test saving and retrieving trained clone model weights for a unique player_id."""
    with tempfile.NamedTemporaryFile(suffix=".pt") as f:
        f.write(b"fake_pt_weights")
        f.flush()

        saved = temp_db.save_model_weights(
            player_id="stuffyness",
            weights_path=f.name,
            model_name="clone",
            val_accuracy=0.612,
            val_loss=1.84,
            save_blob=True,
        )
        assert saved["player_id"] == "stuffyness"
        assert saved["val_accuracy"] == 0.612
        assert saved["val_loss"] == 1.84

        model_rec = temp_db.get_model_weights("stuffyness")
        assert model_rec is not None
        assert model_rec["player_id"] == "stuffyness"
        assert model_rec["val_accuracy"] == 0.612
        assert model_rec["weights_blob"] == b"fake_pt_weights"

        # Update model metrics
        temp_db.save_model_weights(
            player_id="stuffyness",
            weights_path=f.name,
            model_name="clone_v2",
            val_accuracy=0.645,
            val_loss=1.71,
        )
        updated_rec = temp_db.get_model_weights("stuffyness")
        assert updated_rec["model_name"] == "clone_v2"
        assert updated_rec["val_accuracy"] == 0.645


def test_parse_clock_string():
    seconds, clock_str = parse_clock_string("{[%clk 0:09:58.8]}")
    assert seconds == 598.8
    assert clock_str == "9:58.8"

    seconds2, clock_str2 = parse_clock_string("{[%clk 1:15:30]}")
    assert seconds2 == 4530.0
    assert clock_str2 == "1:15:30.0"


def test_csv_import_and_export(temp_db):
    """Test importing games CSV, storing across tables, and exporting back."""
    csv_sample = ROOT / "FINAL_MODEL" / "stuffyness.csv"
    if not csv_sample.is_file():
        pytest.skip("stuffyness.csv not found")

    # Import 2 games
    stats = temp_db.import_games_csv(csv_sample, limit_games=2)
    assert stats["games_imported"] == 2
    assert stats["moves_imported"] > 0

    # User stuffyness should exist
    user = temp_db.get_user("stuffyness")
    assert user is not None

    # 2 games should exist for stuffyness
    games = temp_db.get_games_by_player_id("stuffyness")
    assert len(games) == 2

    # Check moves for first game
    first_game_id = games[0]["game_id"]
    moves = temp_db.get_moves_by_game_id(first_game_id)
    assert len(moves) > 0

    # Export back to CSV
    with tempfile.NamedTemporaryFile(suffix=".csv") as out_f:
        out_csv = temp_db.export_player_games_to_csv("stuffyness", out_f.name)
        assert Path(out_csv).is_file()
        assert Path(out_csv).stat().st_size > 0

