import json
import os
import urllib.request
import helper

# Configuration for local Gemma
DEFAULT_MODEL = "gemma2:2b"
GEMMA_MODEL_ID = os.getenv("GEMMA_MODEL_ID", DEFAULT_MODEL)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
GEMMA_API_URL = os.getenv("GEMMA_API_URL", "")


def _query_local_gemma(prompt: str) -> str:
    """
    Query local Gemma model (default: gemma2:2b) via Ollama or custom local REST API.
    Strictly raises RuntimeError if the local model does not exist or is not running.
    """
    model_name = os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
    print(f"[Gemma] Querying local Gemma model ({model_name})...")

    # 1. Try local Ollama if running
    try:
        req_data = json.dumps({
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=req_data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            if response.status == 200:
                res = json.loads(response.read().decode("utf-8"))
                resp = res.get("response")
                if resp:
                    print(f"[Gemma] Response received from Ollama ({model_name})")
                    return resp
    except Exception as e:
        print(f"[Gemma] Ollama request failed: {e}")

    # 2. Try generic OpenAI-compatible local server (e.g. LiteRT, vLLM, llama.cpp)
    if GEMMA_API_URL:
        try:
            req_data = json.dumps({
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{GEMMA_API_URL}/v1/chat/completions",
                data=req_data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as response:
                if response.status == 200:
                    res = json.loads(response.read().decode("utf-8"))
                    print(f"[Gemma] Response received from local server ({GEMMA_API_URL})")
                    return res["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[Gemma] Local API request failed: {e}")

    # Strict: No graceful/heuristic fallback allowed.
    print(f"[Gemma Error] Local Gemma model ({model_name}) does not exist or is not running.")
    raise RuntimeError(f"Local Gemma model ({model_name}) does not exist or is not running.")


def generate_structured_commentary(game: dict, moves: list[dict], odds: list[float]) -> tuple[list[dict], dict]:
    """
    Generate move-by-move coaching commentary and game narrative strictly with Gemma-e4b.
    Throws RuntimeError if the local model does not exist.
    """
    player = game.get("player_id") or "You"
    opp = game.get("opponent_username") or game.get("opponent") or "Opponent"
    color = (game.get("player_color") or "White").capitalize()
    opp_color = "Black" if color == "White" else "White"
    result = game.get("result") or "Completed"

    # Identify major evaluation swings
    swings = []
    for i in range(len(moves)):
        cur_odds = odds[i] if i < len(odds) else 50.0
        prev_odds = odds[i - 1] if i > 0 and (i - 1) < len(odds) else 50.0
        diff = cur_odds - prev_odds
        swings.append({
            "ply": i,
            "side": moves[i]["side"],
            "move": moves[i]["move"],
            "odds": cur_odds,
            "diff": diff,
        })

    prompt = f"""You are an expert chess coach analyzing a game played by {player} ({color}) vs {opp} ({opp_color}). Result: {result}.
Moves count: {len(moves)}.
Key plies and Stockfish win-odds:
{json.dumps([{'ply': s['ply'], 'move': s['move'], 'odds': round(s['odds'], 1), 'swing': round(s['diff'], 1)} for s in swings[:30]])}

Return valid JSON with:
1. "narrative": 2-3 sentence summary of opening, tactical ideas, pivotal moment, and result.
2. "tags": list of string tags (opening name, blunder type, etc.).
3. "commentary": list of objects each with (ply, phase, headline, text, isPivotal, pivotalLabel).
"""

    raw_response = _query_local_gemma(prompt)
    try:
        parsed = json.loads(raw_response)
        if isinstance(parsed, dict) and "commentary" in parsed:
            return parsed.get("commentary", []), {
                "narrative": parsed.get("narrative", ""),
                "tags": parsed.get("tags", []),
            }
        elif isinstance(parsed, list):
            return parsed, {"narrative": "", "tags": []}
    except Exception:
        if "```json" in raw_response:
            block = raw_response.split("```json")[1].split("```")[0].strip()
            parsed = json.loads(block)
            return parsed.get("commentary", []), {
                "narrative": parsed.get("narrative", ""),
                "tags": parsed.get("tags", []),
            }

    raise RuntimeError(f"Failed to parse response from local Gemma model ({model_name}).")


def get_cached_commentary(game_id: str) -> list[dict] | None:
    """Retrieve cached commentary from SQLite."""
    row = helper.query_one(
        """
        SELECT commentary FROM analyzed_games 
        WHERE (game_id = ? OR game_id = (SELECT game_id FROM games WHERE id = ?))
          AND commentary IS NOT NULL AND commentary != ''
        LIMIT 1
        """,
        (game_id, game_id),
    )
    if row and row.get("commentary"):
        try:
            return json.loads(row["commentary"])
        except Exception:
            return None
    return None


def get_cached_narrative(game_id: str) -> dict | None:
    """Retrieve cached narrative and tags from SQLite."""
    row = helper.query_one(
        """
        SELECT narrative, narrative_tags FROM analyzed_games 
        WHERE (game_id = ? OR game_id = (SELECT game_id FROM games WHERE id = ?))
          AND narrative IS NOT NULL AND narrative != ''
        LIMIT 1
        """,
        (game_id, game_id),
    )
    if row and row.get("narrative"):
        try:
            tags = json.loads(row.get("narrative_tags") or "[]")
        except Exception:
            tags = []
        return {"narrative": row["narrative"], "tags": tags}
    return None


def cache_game_commentary_and_narrative(game_id: str, username: str = None) -> tuple[list[dict], dict]:
    """Ensure commentary and narrative are computed via Gemma and cached in SQLite."""
    cached_c = get_cached_commentary(game_id)
    cached_n = get_cached_narrative(game_id)
    if cached_c is not None and cached_n is not None:
        return cached_c, cached_n

    game = helper.query_one("SELECT * FROM games WHERE game_id = ? OR id = ?", (game_id, game_id))
    if not game:
        return [], {"narrative": "", "tags": []}

    actual_gid = game.get("game_id") or str(game.get("id"))
    uid = username or game.get("player_id") or "stuffyness"

    moves = helper.query(
        "SELECT ply, side, move, time_remaining, clock_str FROM moves WHERE game_id = ? ORDER BY ply ASC",
        (actual_gid,),
    )
    if not moves:
        return [], {"narrative": "", "tags": []}

    # Fetch cached or evaluated odds
    from evaluator import cache_game_odds
    odds = cache_game_odds(actual_gid, uid)

    commentary, narrative = generate_structured_commentary(game, moves, odds)

    helper.execute(
        """
        INSERT INTO analyzed_games (user_id, game_id, commentary, narrative, narrative_tags)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, game_id) DO UPDATE SET 
            commentary = excluded.commentary,
            narrative = excluded.narrative,
            narrative_tags = excluded.narrative_tags
        """,
        (uid, actual_gid, json.dumps(commentary), narrative.get("narrative", ""), json.dumps(narrative.get("tags", []))),
    )

    if game_id != actual_gid:
        helper.execute(
            """
            INSERT INTO analyzed_games (user_id, game_id, commentary, narrative, narrative_tags)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, game_id) DO UPDATE SET 
                commentary = excluded.commentary,
                narrative = excluded.narrative,
                narrative_tags = excluded.narrative_tags
            """,
            (uid, game_id, json.dumps(commentary), narrative.get("narrative", ""), json.dumps(narrative.get("tags", []))),
        )

    return commentary, narrative
