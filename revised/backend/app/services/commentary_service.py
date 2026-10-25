import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from typing import List, Optional, Tuple
from app.config import settings
from app.db.repositories import analysis_repo, game_repo
from app.services.evaluation_service import get_or_calculate_odds

logger = logging.getLogger(__name__)

# Serialize calls to the local Gemma instance to prevent KV cache fragmentation and context overflow
_GEMMA_LOCK = threading.Lock()


def _clean_and_parse_json(raw: str) -> Optional[dict]:
    """Robustly extract and parse JSON from LLM output, handling markdown, truncation, and trailing commas."""
    if not raw:
        return None
    text = raw.strip()

    # 1. Direct JSON parse
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 2. Extract from markdown code blocks (```json ... ``` or ``` ... ```)
    if "```" in text:
        parts = text.split("```")
        for p in parts[1:]:
            cleaned = p.strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
            try:
                data = json.loads(cleaned)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

    # 3. Locate outermost curly braces { ... }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        snippet = text[first_brace : last_brace + 1]
        try:
            data = json.loads(snippet)
            if isinstance(data, dict):
                return data
        except Exception:
            try:
                # Remove trailing commas before closing braces/brackets
                repaired = re.sub(r",\s*([\]}])", r"\1", snippet)
                data = json.loads(repaired)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

    # 4. Handle partially truncated JSON (e.g. if max_tokens cut off trailing braces)
    if first_brace != -1:
        snippet = text[first_brace:].strip()
        open_curlies = snippet.count("{") - snippet.count("}")
        open_brackets = snippet.count("[") - snippet.count("]")
        closed_attempt = snippet + ("]" * max(0, open_brackets)) + ("}" * max(0, open_curlies))
        try:
            data = json.loads(closed_attempt)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    return None


def _query_local_gemma(prompt: str, max_tokens: int = 350) -> str:
    # 1. Try OpenAI-compatible server (llama.cpp server container or vLLM)
    if settings.GEMMA_API_URL:
        req_data = json.dumps({
            "messages": [
                {"role": "system", "content": "You are a concise chess coach. Always respond in valid JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{settings.GEMMA_API_URL.rstrip('/')}/v1/chat/completions",
            data=req_data,
            headers={"Content-Type": "application/json"},
        )
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as response:
                    if response.status == 200:
                        res = json.loads(response.read().decode("utf-8"))
                        content = res["choices"][0]["message"]["content"]
                        if content:
                            return content
                break
            except urllib.error.URLError as e:
                err_str = str(e)
                if ("Connection refused" in err_str or "111" in err_str) and attempt < 3:
                    logger.info("Gemma server initializing, retrying in 4s (attempt %d/4)...", attempt + 1)
                    time.sleep(4)
                    continue
                logger.warning("llama.cpp server request failed: %s", e)
                break
            except Exception as e:
                logger.warning("llama.cpp server request failed: %s", e)
                break

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
            with urllib.request.urlopen(req, timeout=60) as response:
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
            "ply": i + 1,
            "side": moves[i]["side"],
            "move": moves[i]["move"],
            "odds": cur_odds,
            "diff": diff,
        })

    # Pick top pivotal turning points plus opening to keep prompt compact and prevent context overflow
    sorted_by_swing = sorted(swings, key=lambda s: abs(s["diff"]), reverse=True)
    pivotal_plies = [s["ply"] for s in sorted_by_swing[:4]]
    pivotal_plies.extend([1, 2])
    key_swings = [s for s in swings if s["ply"] in set(pivotal_plies)][:6]
    key_swings_str = "; ".join(
        f"ply {s['ply']} ({s['side']} {s['move']}): odds {s['odds']:.0f}% (swing {s['diff']:+.0f}%)"
        for s in key_swings
    )

    top_ply = sorted_by_swing[0]["ply"] if sorted_by_swing else 1
    prompt = f"""You are a master chess coach analyzing {player} ({color}) vs {opp} ({opp_color}). Result: {result}.
Moves: {len(moves)}. Key moments: {key_swings_str}.

Respond in valid JSON with:
1. "narrative": 2 concise coaching sentences summarizing the opening and decisive turning point.
2. "tags": 3 string tags (e.g. ["French Defense", "Tactical Blunder", "Endgame Conversion"]).
3. "commentary": [
     {{"ply": {top_ply}, "phase": "Pivotal Moment", "headline": "Key Turning Point", "text": "Coach advice for this critical position", "isPivotal": true, "pivotalLabel": "Turning Point"}}
   ]
"""

    raw_response = _query_local_gemma(prompt, max_tokens=550)
    parsed = _clean_and_parse_json(raw_response)

    if parsed and isinstance(parsed, dict):
        commentary = parsed.get("commentary", [])
        if not isinstance(commentary, list):
            commentary = [commentary] if isinstance(commentary, dict) else []
        narrative = parsed.get("narrative", "")
        tags = parsed.get("tags", [])
        if not commentary and key_swings:
            top_s = key_swings[0]
            commentary = [{
                "ply": top_s["ply"],
                "phase": "Pivotal Moment",
                "headline": f"Decisive Shift on Move {top_s['ply']}",
                "text": narrative or f"Win-odds swung by {top_s['diff']:+.0f}% after {top_s['side']} played {top_s['move']}.",
                "isPivotal": True,
                "pivotalLabel": "Critical Position"
            }]
        return commentary, {
            "narrative": narrative or f"10-minute game between {player} and {opp}.",
            "tags": tags if isinstance(tags, list) else ["10-Min Rapid"],
        }

    # Clean fallback extraction from raw text without failing
    clean_text = raw_response.strip().replace("```json", "").replace("```", "").strip()
    fallback_commentary = []
    if key_swings:
        top_s = key_swings[0]
        fallback_commentary = [{
            "ply": top_s["ply"],
            "phase": "Pivotal Moment",
            "headline": f"Decisive Shift on Move {top_s['ply']}",
            "text": clean_text[:250] if clean_text else f"Win-odds shifted by {top_s['diff']:+.0f}% after {top_s['side']} played {top_s['move']}.",
            "isPivotal": True,
            "pivotalLabel": "Critical Position"
        }]

    return fallback_commentary, {
        "narrative": clean_text[:350] if clean_text else f"10-minute rapid game played by {player} vs {opp}.",
        "tags": ["10-Min Rapid", "Analyzed Match"],
    }


_ACTIVE_GENERATION_LOCK = threading.Lock()
_ACTIVE_GENERATION_TASKS: set[str] = set()


def is_generation_in_progress(game_id: str) -> bool:
    """Check if Gemma commentary generation is currently active in a background thread."""
    with _ACTIVE_GENERATION_LOCK:
        return game_id in _ACTIVE_GENERATION_TASKS


def start_background_commentary_generation(game_id: str, user_id: Optional[str] = None) -> bool:
    """Launch Gemma commentary generation in an independent background thread if not already running."""
    with _ACTIVE_GENERATION_LOCK:
        if game_id in _ACTIVE_GENERATION_TASKS:
            return False
        _ACTIVE_GENERATION_TASKS.add(game_id)

    def _worker():
        try:
            logger.info("Background Gemma commentary worker started for game %s", game_id)
            get_or_generate_commentary(game_id, user_id)
            logger.info("Background Gemma commentary worker completed for game %s", game_id)
        except Exception as e:
            logger.warning("Background commentary worker error for %s: %s", game_id, e)
        finally:
            with _ACTIVE_GENERATION_LOCK:
                _ACTIVE_GENERATION_TASKS.discard(game_id)

    thread = threading.Thread(target=_worker, name=f"gemma-worker-{game_id}", daemon=True)
    thread.start()
    return True


def get_or_generate_commentary(game_id: str, username: Optional[str] = None) -> Tuple[List[dict], dict]:
    """Retrieve or generate game commentary powered by Gemma, with DB caching."""
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

    try:
        with _GEMMA_LOCK:
            commentary, narrative = generate_structured_commentary(game, moves, odds)
        # Save coaching commentary and narrative immediately into PostgreSQL
        analysis_repo.save_commentary_and_narrative(
            uid, actual_gid, commentary, narrative.get("narrative", ""), narrative.get("tags", [])
        )

        # Compute dense vector embedding asynchronously in background so it never blocks commentary
        def _save_emb_bg():
            try:
                from app.services import embedding_service
                tags_str = ", ".join(narrative.get("tags", []))
                summary_text = f"{narrative.get('narrative', '')} | Themes: {tags_str}"
                emb = embedding_service.get_text_embedding(summary_text)
                if emb:
                    analysis_repo.save_game_embedding(uid, actual_gid, emb)
            except Exception as e:
                logger.debug("Async embedding generation skipped for game '%s': %s", actual_gid, e)

        threading.Thread(target=_save_emb_bg, daemon=True).start()

        return commentary, narrative
    except Exception as e:
        logger.warning("Gemma commentary generation failed for game %s: %s", actual_gid, e)
        return [], {"narrative": "", "tags": []}


def describe_clone_style(player_id: str, refresh: bool = False) -> dict:
    """Generate or retrieve clone playing style profile using Gemma."""
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
        for g in sample_games[:8]
    ) or "Active match history"
    tags_str = ", ".join(metrics.get("sample_tags", [])) or "Dynamic tactical play"
    avg_think = metrics.get("avg_think_time", 1.8)

    prompt = f"""You are a master chess coach. Write a natural language playing style profile for '{player_id}'.
Stats: Avg think: {avg_think}s per move. Recent results: {results_summary}. Traits: {tags_str}.

Return valid JSON with:
1. "style_description": A 2-sentence engaging breakdown of their playing style, tempo, and aggression.
2. "traits": A list of 3 short trait tags (e.g. ["Aggressive Attacker", "Speed Demon", "Tactical Opportunist"]).
"""

    style_desc = None
    traits = []

    try:
        with _GEMMA_LOCK:
            raw_resp = _query_local_gemma(prompt, max_tokens=250)
            parsed = _clean_and_parse_json(raw_resp)
            if parsed and isinstance(parsed, dict):
                style_desc = parsed.get("style_description")
                traits = parsed.get("traits") or []
            elif raw_resp and len(raw_resp.strip()) > 15:
                style_desc = raw_resp.strip().replace("```json", "").replace("```", "").strip()[:250]
                traits = ["Dynamic Playstyle", "Adaptive", "Trained Clone"]
    except Exception as e:
        logger.warning("Gemma style generation failed for %s: %s", opp_clean, e)

    if not style_desc:
        speed_tag = "rapid tactician" if avg_think < 2.0 else "deliberate positional grinder"
        style_desc = (
            f"{player_id.capitalize()} plays as a {speed_tag}, averaging {avg_think}s per move. "
            f"Known for sharp counter-play and practical decision-making in competitive positions."
        )
        traits = ["Sharp Counter-Play", "Dynamic Move Selection", f"Avg {avg_think}s Think"]

    # Update model style immediately in PostgreSQL
    model_repo.update_model_style(opp_clean, style_desc, embedding=None)

    # Compute dense vector embedding in background thread
    def _save_style_emb_bg():
        try:
            from app.services import embedding_service
            traits_str = ", ".join(traits) if isinstance(traits, list) else str(traits)
            emb = embedding_service.get_text_embedding(f"{style_desc} | Persona Traits: {traits_str}")
            if emb:
                model_repo.update_model_style(opp_clean, style_desc, embedding=emb)
        except Exception as e:
            logger.debug("Async style embedding failed for %s: %s", opp_clean, e)

    threading.Thread(target=_save_style_emb_bg, daemon=True).start()

    return {
        "player_id": opp_clean,
        "style_description": style_desc,
        "traits": traits if isinstance(traits, list) else [str(traits)],
        "avg_think_time": avg_think,
        "total_moves_logged": metrics.get("total_moves_logged", 0),
        "cached": False,
    }
