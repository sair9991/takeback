"""
tests/test_backend_pipeline.py - Tests for the 3 backend pipeline functions and eval_stats database field.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import torch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backend.database import Database
from src.backend.model_service import (
    populate_user_data,
    train_model_from_db,
    evaluate_model_and_save_stats,
)


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_chess.db"
        db = Database(db_path=db_path)
        yield db


def test_eval_stats_column_exists_and_persists(temp_db):
    """Test that eval_stats is properly stored and parsed in models table."""
    with tempfile.NamedTemporaryFile(suffix=".pt") as f:
        f.write(b"fake_weights")
        f.flush()

        temp_db.save_model_weights(
            player_id="testuser",
            weights_path=f.name,
            val_accuracy=0.62,
            val_loss=1.85,
        )

        test_stats = {
            "clone_top1_acc": 0.62,
            "maia_top1_acc": 0.54,
            "rel_move_improvement_pct": 14.8,
            "split": "val",
        }
        temp_db.save_model_stats("testuser", test_stats)

        # Retrieve
        fetched_stats = temp_db.get_model_stats("testuser")
        assert fetched_stats is not None
        assert fetched_stats["clone_top1_acc"] == 0.62
        assert fetched_stats["rel_move_improvement_pct"] == 14.8


def test_populate_user_data_without_csv(temp_db):
    """Test that populate_user_data fetches and populates database with zero CSV creation."""
    fake_games = [
        {
            "player_id": "fastplayer",
            "date": "2025.01.01",
            "player_color": "White",
            "time_control": "600",
            "player_elo": 1700,
            "opponent": "Opponent1",
            "opponent_elo": 1750,
            "result": "win",
            "moves": "1. e4 {[%clk 0:09:59.0]} 1... c5 {[%clk 0:09:58.0]} 2. Nf3 {[%clk 0:09:56.5]} 1-0",
        }
    ]

    with patch("src.backend.model_service.fetch_user_games", return_value=fake_games):
        result = populate_user_data("fastplayer", limit=1, db=temp_db)

    assert result["user_id"] == "fastplayer"
    assert result["games_imported"] == 1
    assert result["moves_imported"] == 3

    # Check user in DB
    user = temp_db.get_user("fastplayer")
    assert user is not None

    # Check games in DB
    games = temp_db.get_games_by_player_id("fastplayer")
    assert len(games) == 1
    assert games[0]["result"] == "win"

    # Check moves in DB
    moves = temp_db.get_moves_by_game_id(games[0]["game_id"])
    assert len(moves) == 3
    assert moves[0]["move"] == "e4"
    assert moves[0]["time_remaining"] == 599.0


def test_train_and_evaluate_from_db(temp_db):
    """Test train_model_from_db and evaluate_model_and_save_stats."""
    # Create synthetic snapshots dataset
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        dataset_path = tmp_path / "synthuser_snapshots_dataset.pt"

        N, S, Fdim = 50, 64, 28
        synthetic_tensors = {
            "X": torch.randn(N, S, Fdim),
            "maia_logits": torch.randn(N, S),
            "mask": torch.ones(N, S),
            "target_idx": torch.randint(0, 20, (N,)),
            "seconds": torch.rand(N).mul(20).clamp(min=0.1),
            "game_ids": [f"game_{i // 5}" for i in range(N)],
            "time_label_valid": torch.ones(N, dtype=torch.bool),
        }
        torch.save(synthetic_tensors, dataset_path)

        # Pre-seed user and game in DB
        temp_db.create_or_get_user("synthuser")
        temp_db.insert_game(
            player_id="synthuser",
            src="chess.com",
            player_color="white",
            game_id="game_0",
        )

        # Test train_model_from_db using dataset_path
        train_res = train_model_from_db(
            username="synthuser",
            db=temp_db,
            out_dir=tmp_path,
            epochs=2,
            patience=2,
        )
        assert Path(train_res["weights_path"]).is_file()
        assert "val_accuracy" in train_res

        # Verify weights recorded in DB models table
        model_weights = temp_db.get_model_weights("synthuser")
        assert model_weights is not None
        assert Path(model_weights["weights_path"]).resolve() == Path(train_res["weights_path"]).resolve()

        # Test evaluate_model_and_save_stats
        eval_stats = evaluate_model_and_save_stats(
            username="synthuser",
            db=temp_db,
            dataset_path=dataset_path,
        )
        assert "clone_top1_acc" in eval_stats
        assert "clone_move_nll" in eval_stats

        # Verify eval_stats persisted in the models table
        db_stats = temp_db.get_model_stats("synthuser")
        assert db_stats is not None
        assert db_stats["clone_top1_acc"] == eval_stats["clone_top1_acc"]