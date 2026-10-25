import requests
import pandas as pd
import re
import time
from pathlib import Path

USERNAME = input("Enter your chess.com username: ")
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

df = build_dataframe(USERNAME)
csv_path = Path(__file__).with_name(f"{USERNAME.lower()}.csv")
df.to_csv(csv_path, index=False)
print(df.shape)
print(f"Saved {csv_path.name}")