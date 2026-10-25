# Backend Service & Database

This module provides the database and API services connecting user data from Chess.com / Lichess with the model training and cloning pipeline.

## Database Schema (SQLite)

The database (`data/chess_clone.db`) contains four core tables:

### 1. `users`
Keyed by a unique user ID:
- `user_id` (TEXT PRIMARY KEY) - Target player identifier (e.g. `stuffyness`, `hikaru`).
- `chess_com_username` (TEXT) - Chess.com account username.
- `lichess_username` (TEXT) - Lichess account username.
- `created_at` / `updated_at` (TIMESTAMP)

### 2. `games`
Stores games by player ID:
- `id` (INTEGER PRIMARY KEY AUTOINCREMENT) - Unique internal identifier for the game record.
- `player_id` (TEXT NOT NULL, FOREIGN KEY -> `users.user_id`)
- `game_id` (TEXT) - External platform match identifier or PGN event ID.
- `src` (TEXT) - Data origin (`chess.com` or `lichess`).
- `player_color` (TEXT) - `'white'` or `'black'`.
- `opponent_color` (TEXT) - `'white'` or `'black'`.
- `player_elo` (INTEGER) - Target player rating.
- `opponent_elo` (INTEGER) - Opponent rating.
- `opponent_username` (TEXT) - Opponent handle.
- `result` (TEXT) - Game result (`win`, `loss`, `draw`).
- `time_control` (TEXT) - e.g. `600` or `180+2`.
- `date` (TEXT) - Match date.
- `created_at` (TIMESTAMP)

### 3. `moves`
Stores individual move sequences for each game:
- `id` (INTEGER PRIMARY KEY AUTOINCREMENT)
- `game_id` (TEXT NOT NULL) - Foreign reference to `games.game_id` or `games.id`.
- `ply` (INTEGER NOT NULL) - Move ply order (1, 2, 3...).
- `side` (TEXT NOT NULL) - `'white'` or `'black'`.
- `move` (TEXT NOT NULL) - SAN move notation (e.g. `e4`, `Nf3`).
- `time_remaining` (REAL) - Clock remaining in seconds (e.g. `598.8`).
- `clock_str` (TEXT) - Clock timestamp string (e.g. `0:09:58.8`).
- `created_at` (TIMESTAMP)

### 4. `models`
Tracks trained clone models, weights, and evaluation statistics per user:
- `player_id` (TEXT PRIMARY KEY, FOREIGN KEY -> `users.user_id`)
- `weights_path` (TEXT NOT NULL) - Path to `.pt` checkpoint file on disk.
- `weights_blob` (BLOB) - Optional binary checkpoint payload stored in the database.
- `model_name` (TEXT) - Model name identifier (e.g. `clone`).
- `val_accuracy` (REAL) - Validation accuracy score.
- `val_loss` (REAL) - Validation loss score.
- `eval_stats` (TEXT) - JSON-serialized evaluation and testing metrics vs Maia baseline.
- `created_at` / `updated_at` (TIMESTAMP)

---

## Three Core Backend Pipeline Functions

Exposed in `src/backend/model_service.py`:

```python
from src.backend.model_service import (
    populate_user_data,
    train_model_from_db,
    evaluate_model_and_save_stats,
)

# 1. Populate user data directly into SQLite (NO CSV created)
populate_user_data(username="stuffyness", limit=500)

# 2. Read game data from database, train model, and save weights to models table
train_model_from_db(username="stuffyness")

# 3. Test and evaluate model, saving statistics into models.eval_stats
stats = evaluate_model_and_save_stats(username="stuffyness")
```

---

## Python Usage

```python
from src.backend.database import Database

# Initialize database (defaults to data/chess_clone.db)
db = Database()

# 1. Register or retrieve user
user = db.create_or_get_user("stuffyness", chess_com_username="stuffyness")

# 2. Import games from raw CSV (automatically populates games and moves)
db.import_games_csv("FINAL_MODEL/stuffyness.csv", src="chess.com")

# 3. Query player games and moves
games = db.get_games_by_player_id("stuffyness")
moves = db.get_moves_by_game_id(games[0]["game_id"])

# 4. Save trained clone weights
db.save_model_weights(
    player_id="stuffyness",
    weights_path="FINAL_MODEL/clone.pt",
    val_accuracy=0.62,
    val_loss=1.80,
)

# 5. Fetch model weights for live play
model_info = db.get_model_weights("stuffyness")
```

