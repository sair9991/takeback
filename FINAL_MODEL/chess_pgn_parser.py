import sys
import re
import time
from pathlib import Path

try:
    import requests
except ImportError:
    import urllib.request
    import urllib.error
    import json

    class _RequestsShim:
        class _Response:
            def __init__(self, data: bytes, status_code: int):
                self._data = data
                self.status_code = status_code
                self.text = data.decode("utf-8", errors="replace")
            def json(self):
                return json.loads(self.text)
            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(f"HTTP Error {self.status_code}")

        @staticmethod
        def get(url: str, headers: dict = None):
            req = urllib.request.Request(url, headers=headers or {})
            try:
                with urllib.request.urlopen(req) as resp:
                    return _RequestsShim._Response(resp.read(), resp.status)
            except urllib.error.HTTPError as e:
                return _RequestsShim._Response(e.read(), e.code)

    requests = _RequestsShim()

import pandas as pd

DIR = Path(__file__).resolve().parent
ROOT = DIR.parent
for p in (str(ROOT), str(DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.backend.database import Database

HEADERS = {
    "User-Agent": "chess-pgn-downloader/1.0 (username: your_username; contact: you@example.com)"
}

# Matches each [Tag "value"] pair
TAG_RE = re.compile(r'\[(\w+)\s+"([^"]*)"\]')

def get_archives(username):
    resp = requests.get(f"https://api.chess.com/pub/player/{username}/games/archives", headers=HEADERS)
    resp.raise_for_status()
    return resp.json()["archives"]

def fetch_month_games(archive_url):
    """Monthly JSON. Each game already has time_class and time_control.

    Chess.com sometimes lists the current month before its JSON exists (404).
    None means the caller should read the PGN for that month instead.
    """
    resp = requests.get(archive_url, headers=HEADERS)
    if resp.status_code == 429:
        time.sleep(5)
        resp = requests.get(archive_url, headers=HEADERS)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json().get("games", [])

def fetch_month_pgn(archive_url):
    resp = requests.get(f"{archive_url}/pgn", headers=HEADERS)
    if resp.status_code == 429:
        time.sleep(5)
        resp = requests.get(f"{archive_url}/pgn", headers=HEADERS)
    if resp.status_code == 404:
        return ""
    resp.raise_for_status()
    return resp.text

def split_games(pgn_blob):
    chunks = re.split(r'(?=\[Event )', pgn_blob)
    return [c for c in chunks if c.strip()]

def parse_game_chunk(chunk, username):
    tags = dict(TAG_RE.findall(chunk))

    # Headers and movetext are separated by an empty blank line (\n\n or \r\n\r\n)
    parts = re.split(r'\n\s*\n', chunk.strip(), maxsplit=1)
    movetext = parts[1].strip() if len(parts) > 1 else ""

    is_white = tags.get("White", "").lower() == username.lower()
    result = tags.get("Result", "*")
    if result == "1-0":
        player_result = "win" if is_white else "loss"
    elif result == "0-1":
        player_result = "loss" if is_white else "win"
    else:
        player_result = "draw"

    return {
        "player_id": username.lower(),
        "date": tags.get("Date"),
        "player_color": "White" if is_white else "Black",
        "time_control": tags.get("TimeControl"),
        "player_elo": tags.get("WhiteElo") if is_white else tags.get("BlackElo"),
        "opponent": tags.get("Black") if is_white else tags.get("White"),
        "opponent_elo": tags.get("BlackElo") if is_white else tags.get("WhiteElo"),
        "result": player_result,
        "moves": movetext,
    }

def build_dataframe(username, limit=500):
    # Archives are oldest-first. Walk newest months until `limit` rapid 10|0 games.
    archives = list(reversed(get_archives(username)))
    rows = []
    for i, url in enumerate(archives, start=1):
        print(f"Fetching {url} ({i}/{len(archives)})...")
        games = fetch_month_games(url)
        if games is None:
            print("  JSON archive missing, reading PGN...")
            games = [
                {"pgn": chunk, "time_class": "rapid", "time_control": "600"}
                for chunk in split_games(fetch_month_pgn(url))
                if dict(TAG_RE.findall(chunk)).get("TimeControl") == "600"
            ]
        for game in reversed(games):
            if game.get("time_class") != "rapid" or game.get("time_control") != "600":
                continue
            rows.append(parse_game_chunk(game.get("pgn", ""), username))
            if len(rows) >= limit:
                break
        time.sleep(0.2)
        if len(rows) >= limit:
            break

    rows.reverse()
    return pd.DataFrame(rows)


def fetch_user_games(username: str, limit: int = 500) -> list[dict]:
    """Fetches user games from Chess.com as in-memory dicts without saving any CSV."""
    df = build_dataframe(username, limit=limit)
    return df.to_dict(orient="records")


def fetch_user_games_and_save(username: str, limit: int = 500, out_csv: Path | str | None = None) -> tuple[Path, dict]:
    """
    Fetches games from Chess.com, saves the CSV, stores the username in the db,
    and inserts the games and moves into the SQLite database.
    """
    username = username.strip()
    user_id = username.lower()

    # 1. Store username in db
    db = Database()
    db.create_or_get_user(user_id=user_id, chess_com_username=username)

    # 2. Fetch games and write CSV
    df = build_dataframe(username, limit=limit)
    if out_csv is None:
        out_csv = Path(__file__).resolve().parent / f"{user_id}.csv"
    else:
        out_csv = Path(out_csv)
    df.to_csv(out_csv, index=False)
    print(f"Downloaded {len(df)} games to {out_csv.name}")

    # 3. Add data to games and moves tables in sqlite database
    stats = db.import_games_csv(out_csv, src="chess.com", default_player_id=user_id)
    print(f"Stored in DB: {stats['games_imported']} games, {stats['moves_imported']} moves.")
    return out_csv, stats


if __name__ == "__main__":
    if len(sys.argv) > 1:
        username = sys.argv[1]
    else:
        username = input("Enter your chess.com username: ")
    fetch_user_games_and_save(username)