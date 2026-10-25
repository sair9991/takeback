"""
chess_pgn_parser.py - Self-contained Chess.com API downloader & parser for backend.
Downloads user games from the official Chess.com Public API and formats them for model training.
"""

from __future__ import annotations

import csv
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

HEADERS = {
    "User-Agent": "chess-pgn-downloader/1.0 (ChessCloneApp; contact: support@chessclone.local)",
    "Accept": "application/json",
}

TAG_RE = re.compile(r'\[(\w+)\s+"([^"]*)"\]')
CLK_RE = re.compile(r"\[%clk\s+(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\]")


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(3 + attempt * 2)
                continue
            if e.code == 404:
                return None
            raise
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)
    return None


def _get_text(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(3 + attempt * 2)
                continue
            if e.code == 404:
                return ""
            raise
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)
    return ""


def get_archives(username: str) -> list[str]:
    """Get list of monthly archive URLs for a Chess.com player."""
    clean_user = username.strip().lower()
    url = f"https://api.chess.com/pub/player/{clean_user}/games/archives"
    data = _get_json(url)
    if not data or not isinstance(data, dict):
        return []
    return data.get("archives", [])


def fetch_month_games(archive_url: str) -> list[dict]:
    """Fetches monthly games JSON. Returns [] if not found or empty."""
    data = _get_json(archive_url)
    if not data or not isinstance(data, dict):
        return []
    return data.get("games", [])


def split_games(pgn_blob: str) -> list[str]:
    chunks = re.split(r"(?=\[Event )", pgn_blob)
    return [c for c in chunks if c.strip()]


def parse_game_chunk(chunk: str, username: str) -> Optional[dict[str, Any]]:
    tags = dict(TAG_RE.findall(chunk))
    parts = re.split(r"\n\s*\n", chunk.strip(), maxsplit=1)
    movetext = parts[1].strip() if len(parts) > 1 else ""

    # Must contain clock annotations to be usable for snapshot and think-time prediction
    if not movetext or not CLK_RE.search(movetext):
        return None

    # Strictly keep 10-minute games (10|0 rapid, time_control == "600")
    time_control = str(tags.get("TimeControl", "")).strip()
    if time_control != "600":
        return None

    white_player = tags.get("White", "")
    black_player = tags.get("Black", "")
    is_white = white_player.lower() == username.lower()

    result = tags.get("Result", "*")
    if result == "1-0":
        player_result = "win" if is_white else "loss"
    elif result == "0-1":
        player_result = "loss" if is_white else "win"
    else:
        player_result = "draw"

    return {
        "player_id": username.lower(),
        "date": tags.get("Date", tags.get("UTCDate", "")),
        "player_color": "White" if is_white else "Black",
        "time_control": time_control or "600",
        "player_elo": tags.get("WhiteElo" if is_white else "BlackElo", "1500"),
        "opponent": black_player if is_white else white_player,
        "opponent_elo": tags.get("BlackElo" if is_white else "WhiteElo", "1500"),
        "result": player_result,
        "moves": movetext,
    }


def fetch_user_games(username: str, limit: int = 60) -> list[dict[str, Any]]:
    """
    Downloads live games for username from newest to oldest up to limit.
    """
    clean_user = username.strip().lower()
    archives = list(reversed(get_archives(clean_user)))
    if not archives:
        print(f"[Chess.com] No archives found for '{username}'")
        return []

    rows: list[dict[str, Any]] = []

    for url in archives:
        games = fetch_month_games(url)
        if not games:
            # Fallback to month PGN
            try:
                pgn_text = _get_text(f"{url}/pgn")
                chunks = split_games(pgn_text)
                for c in reversed(chunks):
                    row = parse_game_chunk(c, clean_user)
                    if row:
                        rows.append(row)
                        if len(rows) >= limit:
                            break
            except Exception:
                pass
        else:
            for g in reversed(games):
                # Strictly keep 10-minute games (rapid 10|0, 600 seconds)
                if g.get("time_class") != "rapid" or str(g.get("time_control", "")).strip() != "600":
                    continue
                pgn = g.get("pgn") or ""
                if not pgn:
                    continue
                row = parse_game_chunk(pgn, clean_user)
                if row:
                    rows.append(row)
                    if len(rows) >= limit:
                        break

        time.sleep(0.1)
        if len(rows) >= limit:
            break

    rows.reverse()
    return rows


def fetch_user_games_and_save(
    username: str,
    limit: int = 60,
    out_csv: Optional[Path | str] = None,
) -> tuple[Path, list[dict[str, Any]]]:
    """
    Fetches games for username from Chess.com API and writes to a CSV file.
    """
    clean_user = username.strip().lower()

    games = fetch_user_games(clean_user, limit=limit)
    if not games:
        raise RuntimeError(f"No games found on Chess.com for user '{username}'")

    if out_csv is None:
        out_csv = Path(__file__).resolve().parent.parent.parent.parent / "data" / f"{clean_user}.csv"
    else:
        out_csv = Path(out_csv)

    out_csv.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "player_id",
        "date",
        "player_color",
        "time_control",
        "player_elo",
        "opponent",
        "opponent_elo",
        "result",
        "moves",
    ]

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for g in games:
            writer.writerow({k: g.get(k, "") for k in fieldnames})

    print(f"[Chess.com] Saved {len(games)} games for '{clean_user}' to {out_csv.name}")
    return out_csv, games
