import json
import logging
import urllib.error
import urllib.request
from typing import List, Optional, Tuple
from app.config import settings
from app.db.repositories import analysis_repo, game_repo
from app.services.evaluation_service import get_or_calculate_odds

logger = logging.getLogger(__name__)


def _query_local_gemma(prompt: str) -> str:
    # 1. Try OpenAI-compatible server (llama.cpp server container or vLLM)
    if settings.GEMMA_API_URL:
        try:
            req_data = json.dumps({
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{settings.GEMMA_API_URL.rstrip('/')}/v1/chat/completions",
                data=req_data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as response:
                if response.status == 200:
                    res = json.loads(response.read().decode("utf-8"))
                    content = res["choices"][0]["message"]["content"]
                    if content:
                        return content
        except Exception as e:
            logger.warning("llama.cpp server request failed: %s", e)

    # 2. Try Ollama generate endpoint as fallback
    if settings.OLLAMA_URL:
        try:
            req_data = json.dumps({
                "model": settings.GEMMA_MODEL_ID,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{settings.OLLAMA_URL.rstrip('/')}/api/generate",
                data=req_data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as response:
                if response.status == 200:
                    res = json.loads(response.read().decode("utf-8"))
                    resp = res.get("response")
                    if resp:
                        return resp
        except Exception as e:
            logger.warning("Ollama request failed: %s", e)

    raise RuntimeError(
        f"Gemma model endpoint unreachable at {settings.GEMMA_API_URL or settings.OLLAMA_URL}"
    )


def generate_structured_commentary(game: dict, moves: List[dict], odds: List[float]) -> Tuple[List[dict], dict]:
    player = game.get("player_id") or "You"
    opp = game.get("opponent_username") or "Opponent"
    color = (game.get("player_color") or "White").capitalize()
    opp_color = "Black" if color == "White" else "White"
    result = game.get("result") or "Completed"

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

    raise RuntimeError(f"Failed to parse response from local Gemma model ({settings.GEMMA_MODEL_ID}).")


def get_or_generate_commentary(game_id: str, username: Optional[str] = None) -> Tuple[List[dict], dict]:
    cached = analysis_repo.get_analysis_by_game(game_id, username)
    if cached and cached.get("commentary") and cached.get("narrative"):
        c = cached["commentary"] if isinstance(cached["commentary"], list) else json.loads(cached["commentary"])
        tags = cached.get("narrative_tags") or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []
        return c, {"narrative": cached.get("narrative", ""), "tags": tags}

    game = game_repo.get_game_by_id(game_id)
    if not game:
        return [], {"narrative": "", "tags": []}

    actual_gid = game.get("game_id") or str(game.get("id"))
    uid = username or game.get("player_id") or "stuffyness"
    moves = game_repo.get_game_moves(actual_gid)
    if not moves:
        return [], {"narrative": "", "tags": []}

    odds = get_or_calculate_odds(actual_gid, uid)
    commentary, narrative = generate_structured_commentary(game, moves, odds)
    analysis_repo.save_commentary_and_narrative(
        uid, actual_gid, commentary, narrative.get("narrative", ""), narrative.get("tags", [])
    )
    return commentary, narrative
