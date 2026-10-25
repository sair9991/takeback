"""
setup_db.py - Database initialization and schema creation for the SQLite database.
Run this script to set up tables and indexes in src/database/mock_db.db.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "mock_db.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    chess_com_username TEXT,
    lichess_username TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,
    game_id TEXT,
    src TEXT NOT NULL,
    player_color TEXT NOT NULL,
    opponent_color TEXT NOT NULL,
    player_elo INTEGER,
    opponent_elo INTEGER,
    opponent_username TEXT,
    result TEXT,
    time_control TEXT,
    date TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (player_id) REFERENCES users (user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS moves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    ply INTEGER NOT NULL,
    side TEXT NOT NULL,
    move TEXT NOT NULL,
    time_remaining REAL,
    clock_str TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS models (
    player_id TEXT PRIMARY KEY,
    weights_path TEXT NOT NULL,
    weights_blob BLOB,
    model_name TEXT DEFAULT 'clone',
    val_accuracy REAL,
    val_loss REAL,
    eval_stats TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (player_id) REFERENCES users (user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS analyzed_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    game_id TEXT NOT NULL,
    odds TEXT,
    commentary TEXT,
    narrative TEXT,
    narrative_tags TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, game_id),
    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_games_player_id ON games(player_id);
CREATE INDEX IF NOT EXISTS idx_games_game_id ON games(game_id);
CREATE INDEX IF NOT EXISTS idx_moves_game_id ON moves(game_id);
CREATE INDEX IF NOT EXISTS idx_moves_game_ply ON moves(game_id, ply);
CREATE INDEX IF NOT EXISTS idx_analyzed_user_id ON analyzed_games(user_id);
"""


def setup_database(db_path: Path = DB_PATH):
    """Creates all database tables and indexes if they do not exist."""
    print(f"Setting up database schema at: {db_path}")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        # Migrate existing table if columns missing
        existing_cols = {col[1] for col in conn.execute("PRAGMA table_info(analyzed_games)").fetchall()}
        for col, col_type in [("odds", "TEXT"), ("commentary", "TEXT"), ("narrative", "TEXT"), ("narrative_tags", "TEXT")]:
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE analyzed_games ADD COLUMN {col} {col_type}")
        conn.commit()
    print("Database setup complete.")


if __name__ == "__main__":
    setup_database()
