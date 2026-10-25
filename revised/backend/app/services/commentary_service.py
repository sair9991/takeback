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
    uid = username or game.get("player_id") or "guest"
    moves = game_repo.get_game_moves(actual_gid)
    if not moves:
        return [], {"narrative": "", "tags": []}

    odds = get_or_calculate_odds(actual_gid, uid)
    commentary, narrative = generate_structured_commentary(game, moves, odds)
    analysis_repo.save_commentary_and_narrative(
        uid, actual_gid, commentary, narrative.get("narrative", ""), narrative.get("tags", [])
    )

    # compute dense vector embedding for semantic search
    try:
        from app.services import embedding_service
        tags_str = ", ".join(narrative.get("tags", []))
        summary_text = f"{narrative.get('narrative', '')} | Themes: {tags_str}"
        emb = embedding_service.get_text_embedding(summary_text)
        if emb:
            analysis_repo.save_game_embedding(uid, actual_gid, emb)
    except Exception as e:
        logger.warning("embedding generation error for game '%s': %s", actual_gid, e)

    return commentary, narrative


def describe_clone_style(player_id: str, refresh: bool = False) -> dict:
    """Generate or retrieve a natural language playing style description powered by Gemma."""
    from app.db.repositories import model_repo

    opp_clean = player_id.lower().strip()

    if not refresh:
        stats = model_repo.get_model_stats(opp_clean)
        if stats and stats.get("style_description"):
            return {
                "player_id": opp_clean,
                "style_description": stats["style_description"],
                "traits": ["Personalized Clone"],
                "cached": True,
            }

    metrics = model_repo.get_clone_game_metrics(opp_clean)
    sample_games = metrics.get("sample_games", [])
    results_summary = ", ".join(
        f"{g.get('result', 'draw')} as {g.get('player_color', 'white')}"
        for g in sample_games[:10]
    ) or "Active match history"
    tags_str = ", ".join(metrics.get("sample_tags", [])) or "Dynamic tactical play"
    avg_think = metrics.get("avg_think_time", 1.8)

    prompt = f"""You are a master chess analyst and coach. Write a natural language playing style profile for the chess persona/clone '{player_id}'.
Match statistics:
- Observed thinking speed: {avg_think} seconds per move on average
- Recent sample results: {results_summary}
- Observed match traits: {tags_str}

Return valid JSON with:
1. "style_description": A 2-3 sentence engaging breakdown of their playing style, tempo (fast blitz vs deep think), opening tendencies, and aggression.
2. "traits": A list of 3-4 short trait tags (e.g. ["Aggressive Attacker", "Speed Demon", "Tactical Opportunist"]).
"""

    style_desc = None
    traits = []

    try:
        raw_resp = _query_local_gemma(prompt)
        parsed = json.loads(raw_resp)
        if isinstance(parsed, dict):
            style_desc = parsed.get("style_description")
            traits = parsed.get("traits") or []
    except Exception as e:
        logger.warning("Gemma style generation failed for %s: %s", opp_clean, e)

    if not style_desc:
        speed_tag = "rapid tactician" if avg_think < 2.0 else "deliberate positional grinder"
        style_desc = (
            f"{player_id.capitalize()} plays as a {speed_tag}, averaging {avg_think}s per move. "
            f"Known for sharp counter-play and practical decision-making in competitive positions."
        )
        traits = ["Sharp Counter-Play", "Dynamic Move Selection", f"Avg {avg_think}s Think"]

    emb = None
    try:
        from app.services import embedding_service
        traits_str = ", ".join(traits) if isinstance(traits, list) else str(traits)
        emb = embedding_service.get_text_embedding(f"{style_desc} | Persona Traits: {traits_str}")
    except Exception as e:
        logger.warning("failed to compute style embedding for %s: %s", opp_clean, e)

    model_repo.update_model_style(opp_clean, style_desc, embedding=emb)

    return {
        "player_id": opp_clean,
        "style_description": style_desc,
        "traits": traits if isinstance(traits, list) else [str(traits)],
        "avg_think_time": avg_think,
        "total_moves_logged": metrics.get("total_moves_logged", 0),
        "cached": False,
    }
