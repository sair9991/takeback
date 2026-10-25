"""
src/backend/database.py - SQLite Database management for the Chess Clone Backend.

Tables:
  1. users:
     - user_id (TEXT PRIMARY KEY, same as player_id)
     - chess_com_username (TEXT)
     - lichess_username (TEXT)
     - created_at, updated_at (TIMESTAMP)

  2. games:
     - id (INTEGER PRIMARY KEY AUTOINCREMENT) -> unique id for each player's game
     - player_id (TEXT, foreign key -> users.user_id)
     - game_id (TEXT) -> platform or PGN game identifier
     - src (TEXT) -> 'chess.com' or 'lichess'
     - player_color (TEXT) -> 'white' or 'black'
     - opponent_color (TEXT) -> 'black' or 'white'
     - player_elo (INTEGER)
     - opponent_elo (INTEGER)
     - opponent_username (TEXT)
     - result (TEXT) -> 'win', 'loss', 'draw'
     - time_control (TEXT)
     - date (TEXT)
     - created_at (TIMESTAMP)

  3. moves:
     - id (INTEGER PRIMARY KEY AUTOINCREMENT)
     - game_id (TEXT) -> references games table (game_id or game record id)
     - ply (INTEGER) -> move sequence index (1, 2, 3...)
     - side (TEXT) -> 'white' or 'black'
     - move (TEXT) -> SAN string (e.g. 'e4', 'Nf3')
     - time_remaining (REAL) -> remaining clock in seconds (e.g. 598.8)
     - clock_str (TEXT) -> raw clock timestamp (e.g. '0:09:58.8')
     - created_at (TIMESTAMP)

  4. models:
     - player_id (TEXT PRIMARY KEY, foreign key -> users.user_id)
     - weights_path (TEXT) -> path to .pt file on disk
     - weights_blob (BLOB) -> optional binary weights in database
     - model_name (TEXT)
     - val_accuracy (REAL)
     - val_loss (REAL)
     - created_at, updated_at (TIMESTAMP)
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

import chess
import chess.pgn

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = ROOT / "data" / "chess_clone.db"

# Clock comment regex: [%clk H:MM:SS(.s)] or [%clk M:SS(.s)]
CLK_RE = re.compile(r"\[%clk\s+(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\]")


def parse_clock_string(comment: str) -> tuple[Optional[float], Optional[str]]:
    """Extracts seconds remaining and clock text from a PGN comment like '{[%clk 0:09:58.8]}'."""
    if not comment:
        return None, None
    m = CLK_RE.search(comment)
    if not m:
        return None, None
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2))
    seconds = float(m.group(3))
    total_seconds = round(hours * 3600 + minutes * 60 + seconds, 3)
    clock_raw = f"{hours}:{minutes:02d}:{seconds:04.1f}" if hours else f"{minutes}:{seconds:04.1f}"
    return total_seconds, clock_raw


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

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

CREATE INDEX IF NOT EXISTS idx_games_player_id ON games(player_id);
CREATE INDEX IF NOT EXISTS idx_games_game_id ON games(game_id);
CREATE INDEX IF NOT EXISTS idx_moves_game_id ON moves(game_id);
CREATE INDEX IF NOT EXISTS idx_moves_game_ply ON moves(game_id, ply);
"""


class Database:
    """Manages SQLite connections and queries for the chess clone backend."""

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @contextmanager
    def session(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        """Executes table schemas and initial indexes."""
        with self.session() as conn:
            conn.executescript(SCHEMA_SQL)
            try:
                conn.execute("ALTER TABLE models ADD COLUMN eval_stats TEXT;")
            except sqlite3.OperationalError:
                pass

    # ----------------------------------------------------------------------- #
    # 1. Users Table Operations
    # ----------------------------------------------------------------------- #
    def create_or_get_user(
        self,
        user_id: str,
        chess_com_username: Optional[str] = None,
        lichess_username: Optional[str] = None,
    ) -> dict[str, Any]:
        """Creates user if not present, or updates accounts if provided."""
        user_id_clean = user_id.strip()
        with self.session() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id_clean,)
            ).fetchone()

            if row is None:
                conn.execute(
                    """
                    INSERT INTO users (user_id, chess_com_username, lichess_username)
                    VALUES (?, ?, ?)
                    """,
                    (user_id_clean, chess_com_username, lichess_username),
                )
            else:
                updates = []
                params = []
                if chess_com_username and chess_com_username != row["chess_com_username"]:
                    updates.append("chess_com_username = ?")
                    params.append(chess_com_username)
                if lichess_username and lichess_username != row["lichess_username"]:
                    updates.append("lichess_username = ?")
                    params.append(lichess_username)

                if updates:
                    updates.append("updated_at = CURRENT_TIMESTAMP")
                    params.append(user_id_clean)
                    conn.execute(
                        f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?",
                        tuple(params),
                    )

            res = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id_clean,)).fetchone()
            return dict(res)

    def get_user(self, user_id: str) -> Optional[dict[str, Any]]:
        with self.session() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    # ----------------------------------------------------------------------- #
    # 2. Games Table Operations
    # ----------------------------------------------------------------------- #
    def insert_game(
        self,
        player_id: str,
        src: str,
        player_color: str,
        opponent_color: Optional[str] = None,
        player_elo: Optional[int] = None,
        opponent_elo: Optional[int] = None,
        opponent_username: Optional[str] = None,
        result: Optional[str] = None,
        game_id: Optional[str] = None,
        time_control: Optional[str] = None,
        date: Optional[str] = None,
    ) -> int:
        """
        Inserts a single game keyed by player_id. Returns the auto-generated game primary key id.
        """
        player_id_clean = player_id.strip()
        # Automatically make sure user exists
        chess_com = player_id_clean if src == "chess.com" else None
        lichess = player_id_clean if src == "lichess" else None
        self.create_or_get_user(player_id_clean, chess_com_username=chess_com, lichess_username=lichess)

        p_color = player_color.strip().lower()
        if not opponent_color:
            opponent_color = "black" if p_color == "white" else "white"
        opp_color = opponent_color.strip().lower()

        with self.session() as conn:
            cur = conn.execute(
                """
                INSERT INTO games (
                    player_id, game_id, src, player_color, opponent_color,
                    player_elo, opponent_elo, opponent_username, result,
                    time_control, date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    player_id_clean,
                    str(game_id) if game_id else None,
                    src,
                    p_color,
                    opp_color,
                    player_elo,
                    opponent_elo,
                    opponent_username,
                    result,
                    time_control,
                    date,
                ),
            )
            return cur.lastrowid

    def get_game_by_id(self, game_pk: int) -> Optional[dict[str, Any]]:
        with self.session() as conn:
            row = conn.execute("SELECT * FROM games WHERE id = ?", (game_pk,)).fetchone()
            return dict(row) if row else None

    def get_games_by_player_id(self, player_id: str) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT * FROM games WHERE player_id = ? ORDER BY id ASC",
                (player_id.strip(),),
            ).fetchall()
            return [dict(r) for r in rows]

    # ----------------------------------------------------------------------- #
    # 3. Moves Table Operations
    # ----------------------------------------------------------------------- #
    def insert_moves(self, game_id: str | int, moves: list[dict[str, Any]]) -> int:
        """
        Bulk inserts move records for a game id.
        Each move dict expected keys: ply, side, move, time_remaining, clock_str.
        """
        records = [
            (
                str(game_id),
                m["ply"],
                m["side"].strip().lower(),
                m["move"].strip(),
                m.get("time_remaining"),
                m.get("clock_str"),
            )
            for m in moves
        ]
        with self.session() as conn:
            conn.executemany(
                """
                INSERT INTO moves (game_id, ply, side, move, time_remaining, clock_str)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                records,
            )
        return len(records)

    def get_moves_by_game_id(self, game_id: str | int) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT * FROM moves WHERE game_id = ? ORDER BY ply ASC",
                (str(game_id),),
            ).fetchall()
            return [dict(r) for r in rows]

    # ----------------------------------------------------------------------- #
    # 4. Models Table Operations
    # ----------------------------------------------------------------------- #
    def save_model_weights(
        self,
        player_id: str,
        weights_path: str | Path,
        model_name: str = "clone",
        val_accuracy: Optional[float] = None,
        val_loss: Optional[float] = None,
        eval_stats: Optional[dict[str, Any] | str] = None,
        save_blob: bool = False,
    ) -> dict[str, Any]:
        """
        Saves or updates model weights and performance metrics for a unique player_id.
        """
        player_id_clean = player_id.strip()
        self.create_or_get_user(player_id_clean)
        path_str = str(Path(weights_path).resolve())

        weights_blob = None
        if save_blob and Path(weights_path).is_file():
            with open(weights_path, "rb") as f:
                weights_blob = f.read()

        stats_str = json.dumps(eval_stats) if isinstance(eval_stats, dict) else (str(eval_stats) if eval_stats else None)

        with self.session() as conn:
            conn.execute(
                """
                INSERT INTO models (player_id, weights_path, weights_blob, model_name, val_accuracy, val_loss, eval_stats, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(player_id) DO UPDATE SET
                    weights_path = excluded.weights_path,
                    weights_blob = coalesce(excluded.weights_blob, models.weights_blob),
                    model_name = excluded.model_name,
                    val_accuracy = coalesce(excluded.val_accuracy, models.val_accuracy),
                    val_loss = coalesce(excluded.val_loss, models.val_loss),
                    eval_stats = coalesce(excluded.eval_stats, models.eval_stats),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (player_id_clean, path_str, weights_blob, model_name, val_accuracy, val_loss, stats_str),
            )
            row = conn.execute("SELECT * FROM models WHERE player_id = ?", (player_id_clean,)).fetchone()
            return dict(row)

    def save_model_stats(self, player_id: str, eval_stats: dict[str, Any] | str) -> dict[str, Any]:
        """Updates the evaluation statistics field for a player's model in the models table."""
        player_id_clean = player_id.strip()
        stats_str = json.dumps(eval_stats) if isinstance(eval_stats, dict) else str(eval_stats)
        with self.session() as conn:
            conn.execute(
                """
                UPDATE models
                SET eval_stats = ?, updated_at = CURRENT_TIMESTAMP
                WHERE player_id = ?
                """,
                (stats_str, player_id_clean),
            )
            row = conn.execute("SELECT * FROM models WHERE player_id = ?", (player_id_clean,)).fetchone()
            return dict(row) if row else {}

    def get_model_stats(self, player_id: str) -> Optional[dict[str, Any]]:
        with self.session() as conn:
            row = conn.execute("SELECT eval_stats FROM models WHERE player_id = ?", (player_id.strip(),)).fetchone()
            if row and row["eval_stats"]:
                try:
                    return json.loads(row["eval_stats"])
                except Exception:
                    return {"raw": row["eval_stats"]}
            return None

    def get_model_weights(self, player_id: str) -> Optional[dict[str, Any]]:
        with self.session() as conn:
            row = conn.execute("SELECT * FROM models WHERE player_id = ?", (player_id.strip(),)).fetchone()
            return dict(row) if row else None

    def import_games_list(
        self,
        games: list[dict[str, Any]],
        default_player_id: Optional[str] = None,
        src: str = "chess.com",
    ) -> dict[str, int]:
        """
        Populates database directly from in-memory game dicts without writing any CSV files.
        """
        games_imported = 0
        moves_imported = 0

        for i, row in enumerate(games):
            player_id = (row.get("player_id") or default_player_id or "").strip()
            if not player_id:
                continue

            player_color = (row.get("player_color") or "white").strip().lower()
            opponent_color = "black" if player_color == "white" else "white"

            def _safe_int(val: Any) -> Optional[int]:
                try:
                    return int(float(str(val).strip()))
                except (ValueError, TypeError):
                    return None

            player_elo = _safe_int(row.get("player_elo"))
            opponent_elo = _safe_int(row.get("opponent_elo"))
            opponent_username = (row.get("opponent") or "").strip()
            result = (row.get("result") or "").strip().lower()
            time_control = (row.get("time_control") or "").strip()
            date = (row.get("date") or "").strip()
            external_game_id = str(row.get("game_id") or row.get("moves_ID") or f"{player_id}_{date}_{i}")

            # 1. Insert Game Record
            self.insert_game(
                player_id=player_id,
                src=src,
                player_color=player_color,
                opponent_color=opponent_color,
                player_elo=player_elo,
                opponent_elo=opponent_elo,
                opponent_username=opponent_username,
                result=result,
                game_id=external_game_id,
                time_control=time_control,
                date=date,
            )
            games_imported += 1

            # 2. Parse Movetext into Individual Moves in-memory
            movetext = row.get("moves") or ""
            if movetext.strip():
                try:
                    game_pgn = chess.pgn.read_game(io.StringIO(movetext))
                except Exception:
                    game_pgn = None

                if game_pgn is not None:
                    board = game_pgn.board()
                    game_moves = []
                    for ply, node in enumerate(game_pgn.mainline(), start=1):
                        side = "white" if board.turn == chess.WHITE else "black"
                        san = board.san(node.move)
                        seconds, clock_str = parse_clock_string(node.comment)
                        game_moves.append({
                            "ply": ply,
                            "side": side,
                            "move": san,
                            "time_remaining": seconds,
                            "clock_str": clock_str or node.comment,
                        })
                        board.push(node.move)

                    if game_moves:
                        self.insert_moves(game_id=external_game_id, moves=game_moves)
                        moves_imported += len(game_moves)

        return {"games_imported": games_imported, "moves_imported": moves_imported}

    # ----------------------------------------------------------------------- #
    # Integration: CSV Importer & Exporter
    # ----------------------------------------------------------------------- #
    def import_games_csv(
        self,
        csv_path: str | Path,
        src: str = "chess.com",
        default_player_id: Optional[str] = None,
        limit_games: Optional[int] = None,
    ) -> dict[str, int]:
        """
        Parses games CSV (such as stuffyness.csv or games.csv) and populates:
          - users table
          - games table
          - moves table (parsed from PGN movetext with clock annotations)
        """
        path = Path(csv_path)
        if not path.is_file():
            raise FileNotFoundError(f"CSV file not found: {path}")

        games_imported = 0
        moves_imported = 0

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if limit_games and i >= limit_games:
                    break

                player_id = (row.get("player_id") or default_player_id or "").strip()
                if not player_id:
                    continue

                player_color = (row.get("player_color") or "white").strip().lower()
                opponent_color = "black" if player_color == "white" else "white"

                def _safe_int(val: Any) -> Optional[int]:
                    try:
                        return int(float(str(val).strip()))
                    except (ValueError, TypeError):
                        return None

                player_elo = _safe_int(row.get("player_elo"))
                opponent_elo = _safe_int(row.get("opponent_elo"))
                opponent_username = (row.get("opponent") or "").strip()
                result = (row.get("result") or "").strip().lower()
                time_control = (row.get("time_control") or "").strip()
                date = (row.get("date") or "").strip()
                external_game_id = str(row.get("game_id") or row.get("moves_ID") or f"{player_id}_{date}_{i}")

                # 1. Insert Game Record
                game_pk = self.insert_game(
                    player_id=player_id,
                    src=src,
                    player_color=player_color,
                    opponent_color=opponent_color,
                    player_elo=player_elo,
                    opponent_elo=opponent_elo,
                    opponent_username=opponent_username,
                    result=result,
                    game_id=external_game_id,
                    time_control=time_control,
                    date=date,
                )
                games_imported += 1

                # 2. Parse Movetext into Individual Moves
                movetext = row.get("moves") or ""
                if movetext.strip():
                    try:
                        game_pgn = chess.pgn.read_game(io.StringIO(movetext))
                    except Exception:
                        game_pgn = None

                    if game_pgn is not None:
                        board = game_pgn.board()
                        game_moves = []
                        for ply, node in enumerate(game_pgn.mainline(), start=1):
                            side = "white" if board.turn == chess.WHITE else "black"
                            san = board.san(node.move)
                            seconds, clock_str = parse_clock_string(node.comment)
                            game_moves.append({
                                "ply": ply,
                                "side": side,
                                "move": san,
                                "time_remaining": seconds,
                                "clock_str": clock_str or node.comment,
                            })
                            board.push(node.move)

                        if game_moves:
                            self.insert_moves(game_id=external_game_id, moves=game_moves)
                            moves_imported += len(game_moves)

        return {"games_imported": games_imported, "moves_imported": moves_imported}

    def export_player_games_to_csv(self, player_id: str, output_csv: str | Path) -> str:
        """
        Reconstructs games and moves for a player into the pipeline's expected CSV format.
        """
        games = self.get_games_by_player_id(player_id)
        out_path = Path(output_csv)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "player_id", "date", "player_color", "time_control",
            "player_elo", "opponent", "opponent_elo", "result", "moves"
        ]

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for g in games:
                ext_game_id = g.get("game_id") or str(g["id"])
                move_rows = self.get_moves_by_game_id(ext_game_id)

                # Reconstruct PGN movetext with clock annotations
                movetext_parts = []
                for m in move_rows:
                    ply = m["ply"]
                    move_san = m["move"]
                    clk = m.get("clock_str") or (f"{m['time_remaining']:.1f}" if m.get("time_remaining") is not None else "")
                    clk_annotation = f" {{[%clk {clk}]}}" if clk else ""

                    if ply % 2 == 1:
                        movenum = (ply + 1) // 2
                        movetext_parts.append(f"{movenum}. {move_san}{clk_annotation}")
                    else:
                        movetext_parts.append(f"{move_san}{clk_annotation}")

                movetext = " ".join(movetext_parts)
                writer.writerow({
                    "player_id": g["player_id"],
                    "date": g["date"] or "",
                    "player_color": g["player_color"].capitalize(),
                    "time_control": g["time_control"] or "600",
                    "player_elo": g["player_elo"] or "",
                    "opponent": g["opponent_username"] or "",
                    "opponent_elo": g["opponent_elo"] or "",
                    "result": g["result"] or "",
                    "moves": movetext,
                })

        return str(out_path)

