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


def _query_local_gemma(prompt: str, max_tokens: int = 550) -> str:
    """Query local Gemma model with robust timeout and multi-endpoint fallback (OpenAI, llama.cpp native, Ollama)."""
    timeout_sec = getattr(settings, "GEMMA_TIMEOUT", 60.0)

    # 1. Try OpenAI-compatible server (llama.cpp server or vLLM)
    if settings.GEMMA_API_URL:
        api_url = settings.GEMMA_API_URL.rstrip("/")
        # Try /v1/chat/completions first
        req_data = json.dumps({
            "messages": [
                {"role": "system", "content": "You are a master chess coach. Respond ONLY in valid JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{api_url}/v1/chat/completions",
            data=req_data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as response:
                if response.status == 200:
                    res = json.loads(response.read().decode("utf-8"))
                    content = res.get("choices", [{}])[0].get("message", {}).get("content")
                    if content:
                        return content
        except Exception as e:
            logger.debug("Gemma chat/completions skipped (%s): %s", api_url, e)

        # Fallback to native llama.cpp /completion endpoint
        try:
            native_data = json.dumps({
                "prompt": f"<start_of_turn>user\nYou are a master chess coach. Respond ONLY in valid JSON.\n{prompt}<end_of_turn>\n<start_of_turn>model\n",
                "temperature": 0.2,
                "n_predict": max_tokens,
            }).encode("utf-8")
            native_req = urllib.request.Request(
                f"{api_url}/completion",
                data=native_data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(native_req, timeout=timeout_sec) as response:
                if response.status == 200:
                    res = json.loads(response.read().decode("utf-8"))
                    content = res.get("content")
                    if content:
                        return content
        except Exception as e:
            logger.debug("llama.cpp native /completion skipped: %s", e)

    # 2. Try Ollama generate/chat endpoint as fallback
    ollama_candidates = [settings.OLLAMA_URL] if settings.OLLAMA_URL else []
    if "http://localhost:11434" not in ollama_candidates and "http://127.0.0.1:11434" not in ollama_candidates:
        ollama_candidates.append("http://localhost:11434")

    for o_url in ollama_candidates:
        if not o_url:
            continue
        try:
            req_data = json.dumps({
                "model": settings.GEMMA_MODEL_ID,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{o_url.rstrip('/')}/api/generate",
                data=req_data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout_sec) as response:
                if response.status == 200:
                    res = json.loads(response.read().decode("utf-8"))
                    resp = res.get("response")
                    if resp:
                        return resp
        except Exception as e:
            logger.debug("Ollama request skipped for %s: %s", o_url, e)

    return ""


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

    # Pick opening plies, top decisive swings, and the conclusion
    sorted_by_swing = sorted(swings, key=lambda s: abs(s["diff"]), reverse=True)
    key_plies = set()
    # Add opening
    if len(moves) >= 1:
        key_plies.add(1)
    if len(moves) >= 2:
        key_plies.add(2)
    # Add top 4 critical evaluation swings
    for s in sorted_by_swing[:4]:
        key_plies.add(s["ply"])
    # Add endgame / final move
    if len(moves) >= 4:
        key_plies.add(len(moves))

    key_swings = [s for s in swings if s["ply"] in key_plies]
    key_swings.sort(key=lambda s: s["ply"])

    key_swings_str = "; ".join(
        f"ply {s['ply']} ({s['side']} {s['move']}): player win-odds {s['odds']:.0f}% (swing {s['diff']:+.0f}%)"
        for s in key_swings
    )

    prompt = f"""You are a master chess coach analyzing a match between {player} ({color}) and {opp} ({opp_color}). Result: {result}.
Total plies: {len(moves)}.
Key moments from engine evaluation:
{key_swings_str}

Analyze this game and return valid JSON with:
1. "narrative": 2-3 concise, engaging coaching sentences summarizing the opening, key decisive turning points, and match conclusion.
2. "tags": 3-5 tags (e.g. ["Italian Game", "Tactical Blunder", "Kingside Attack", "Endgame Conversion"]).
3. "commentary": A list of commentary objects covering each of the key plies mentioned above.
Each object must have:
- "ply": integer ply number (1-indexed)
- "phase": string ("Opening", "Middlegame", "Tactical Turn", "Blunder", or "Endgame")
- "headline": punchy catchphrase (3-6 words)
- "text": 1-2 coaching sentences explaining the position, mistakes, and tactical ideas
- "isPivotal": boolean (true for major turning points / swings >= 15%)
- "pivotalLabel": string ("Blunder", "Turning Point", "Missed Win", "Brilliant Move", or "Critical Position")
"""

    raw_response = _query_local_gemma(prompt, max_tokens=700)
    parsed = _clean_and_parse_json(raw_response)

    if parsed and isinstance(parsed, dict):
        commentary = parsed.get("commentary", [])
        if not isinstance(commentary, list):
            commentary = [commentary] if isinstance(commentary, dict) else []
        narrative = parsed.get("narrative", "")
        tags = parsed.get("tags", [])

        # Validate commentary items
        valid_commentary = []
        for c in commentary:
            if isinstance(c, dict) and "ply" in c:
                valid_commentary.append({
                    "ply": int(c["ply"]),
                    "phase": str(c.get("phase") or "Analysis"),
                    "headline": str(c.get("headline") or f"Move {c['ply']}"),
                    "text": str(c.get("text") or ""),
                    "isPivotal": bool(c.get("isPivotal") or c.get("is_pivotal")),
                    "pivotalLabel": str(c.get("pivotalLabel") or c.get("pivotal_label") or "Turning Point"),
                    "pivotalId": f"moment-{c['ply']}",
                })

        if valid_commentary:
            return valid_commentary, {
                "narrative": narrative or f"Match between {player} ({color}) and {opp} ({opp_color}), concluding in {result}.",
                "tags": tags if isinstance(tags, list) and tags else ["Analyzed Game", "Gemma Coach"],
            }

    # Rich, structured fallback across all key moments if LLM response was unavailable
    fallback_commentary = []
    # 1. Opening moment
    if len(moves) >= 2:
        m1 = moves[0]["move"]
        m2 = moves[1]["move"]
        fallback_commentary.append({
            "ply": 2,
            "phase": "Opening",
            "headline": f"Opening Phase ({m1} / {m2})",
            "text": f"Both {player} and {opp} contest the center early with {m1} and {m2}, setting the initial pawn structure.",
            "isPivotal": False,
            "pivotalLabel": "Opening",
            "pivotalId": "moment-2",
        })

    # 2. Critical swings
    for s in sorted_by_swing[:3]:
        swing_val = abs(s["diff"])
        if swing_val >= 18:
            is_blunder = s["diff"] < 0
            label = "Blunder" if is_blunder else "Decisive Advantage"
            headline = f"Major Turning Point on Move {s['ply']}"
            text = f"Win-odds shifted by {s['diff']:+.0f}% after {s['side']} played {s['move']}. A critical turning point in the game."
        elif swing_val >= 8:
            label = "Inaccuracy"
            headline = f"Tactical Shift on Move {s['ply']}"
            text = f"Evaluation shifted by {s['diff']:+.0f}% after {s['side']} played {s['move']}."
        else:
            continue

        fallback_commentary.append({
            "ply": s["ply"],
            "phase": "Tactical Turn" if swing_val < 18 else "Critical Moment",
            "headline": headline,
            "text": text,
            "isPivotal": swing_val >= 15,
            "pivotalLabel": label,
            "pivotalId": f"moment-{s['ply']}",
        })

    # 3. Final move / conclusion
    if len(moves) >= 4 and len(moves) not in [c["ply"] for c in fallback_commentary]:
        last_m = moves[-1]
        fallback_commentary.append({
            "ply": len(moves),
            "phase": "Endgame",
            "headline": f"Game Finish: {result.capitalize()}",
            "text": f"Match concluded after {len(moves)} plies with result '{result}'.",
            "isPivotal": False,
            "pivotalLabel": "Result",
            "pivotalId": f"moment-{len(moves)}",
        })

    fallback_commentary.sort(key=lambda c: c["ply"])

    top_s = sorted_by_swing[0] if sorted_by_swing else None
    if top_s and abs(top_s["diff"]) >= 15:
        summary_narrative = (
            f"{player} ({color}) faced {opp} ({opp_color}) ending in {result}. "
            f"The game swung decisively on ply {top_s['ply']} ({top_s['side']} {top_s['move']}) with a {top_s['diff']:+.0f}% shift."
        )
    else:
        summary_narrative = f"A hard-fought {len(moves)}-ply match between {player} and {opp}, concluding with {result}."

    return fallback_commentary, {
        "narrative": summary_narrative,
        "tags": ["Analyzed Match", f"{color} vs {opp_color}", "Pivotal Moments"],
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
        narrative_text = cached.get("narrative", "")
        is_bland = any(p in narrative_text.lower() for p in ["10-minute game between", "10-minute rapid game played by"])
        if not is_bland:
            tags = cached.get("narrative_tags") or []
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = []
            return c, {"narrative": narrative_text, "tags": tags}

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
    """Generate or retrieve clone playing style profile using Gemma or dynamic game analysis."""
    from app.db.repositories import model_repo

    opp_clean = player_id.lower().strip()

    if not refresh:
        stats = model_repo.get_model_stats(opp_clean)
        if stats and stats.get("style_description"):
            existing = stats["style_description"]
            is_bland = any(
                p in existing.lower()
                for p in ["adaptive neural chess clone", "trained on personal games"]
            )
            if not is_bland:
                return {
                    "player_id": opp_clean,
                    "style_description": existing,
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
        logger.debug("Gemma style generation skipped for %s: %s", opp_clean, e)

    if not style_desc:
        display_name = player_id.capitalize()
        total_games = len(sample_games)
        wins = sum(1 for g in sample_games if g.get("result") in ("win", "1-0"))
        win_rate = int(round((wins / total_games) * 100)) if total_games > 0 else None

        if avg_think < 1.4:
            speed_tag = "lightning-fast blitzer"
            tempo_desc = f"moving in an average of {avg_think}s per ply to pressure the clock"
        elif avg_think < 2.2:
            speed_tag = "rapid tactical striker"
            tempo_desc = f"averaging {avg_think}s per move with swift calculation"
        else:
            speed_tag = "deliberate positional grinder"
            tempo_desc = f"investing {avg_think}s per move to find deep defensive resources"

        tags = metrics.get("sample_tags", [])
        tactical_tag = tags[0] if tags else "sharp counter-play"

        if win_rate is not None and total_games >= 3:
            style_desc = (
                f"{display_name} plays as a {speed_tag}, {tempo_desc} with a {win_rate}% win rate across recent matches. "
                f"Known for {tactical_tag.lower()} and clinical conversion in high-stakes positions."
            )
        else:
            style_desc = (
                f"{display_name} plays as a {speed_tag}, {tempo_desc}. "
                f"Specializes in dynamic piece coordination, proactive opening initiative, and sharp {tactical_tag.lower()}."
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
