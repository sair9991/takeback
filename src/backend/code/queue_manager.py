import asyncio
import json
import time
import evaluator
import gemma_service
import helper

queue = asyncio.Queue()
jobs = {}
listeners = {}


def is_cached(opp: str) -> bool:
    return bool(helper.query_one("SELECT 1 FROM models WHERE LOWER(player_id) = LOWER(?)", (opp,)))


async def broadcast(job_id: str, data: dict):
    jobs[job_id].update(data)
    for q in listeners.get(job_id, []):
        await q.put(json.dumps(jobs[job_id]))


async def worker():
    while True:
        job = await queue.get()
        job_id, opp, uid, gid = job["id"], job["opp"], job["uid"], job["gid"]

        for step, pct, msg in [
            ("fetching_data", 25, f"Fetching games for {opp}"),
            ("features", 60, "Extracting move features"),
            ("training", 90, "Training clone model"),
        ]:
            await broadcast(job_id, {"status": step, "progress": pct, "message": msg})
            await asyncio.sleep(1)

        helper.execute(
            "INSERT OR REPLACE INTO models (player_id, weights_path) VALUES (?, ?)",
            (opp.lower(), f"models/{opp.lower()}.pt"),
        )
        if uid and gid:
            try:
                await asyncio.to_thread(evaluator.cache_game_odds, gid, uid)
                await asyncio.to_thread(gemma_service.cache_game_commentary_and_narrative, gid, uid)
            except Exception as e:
                print(f"Error caching analysis for {gid}: {e}")
            helper.execute("INSERT OR IGNORE INTO analyzed_games (user_id, game_id) VALUES (?, ?)", (uid, gid))

        await broadcast(job_id, {"status": "completed", "progress": 100, "message": f"Model for {opp} cached"})
        queue.task_done()


def enqueue(opp: str, uid: str, gid: str) -> str:
    job_id = f"train_{opp.lower()}_{int(time.time())}"
    jobs[job_id] = {"id": job_id, "opp": opp, "status": "queued", "progress": 0}
    listeners[job_id] = []
    queue.put_nowait({"id": job_id, "opp": opp, "uid": uid, "gid": gid})
    return job_id


async def stream(job_id: str):
    if job_id not in jobs:
        yield f"data: {json.dumps({'error': 'Job not found'})}\n\n"
        return

    yield f"data: {json.dumps(jobs[job_id])}\n\n"
    if jobs[job_id]["status"] == "completed":
        return

    q = asyncio.Queue()
    listeners[job_id].append(q)
    try:
        while True:
            msg = await q.get()
            yield f"data: {msg}\n\n"
            if json.loads(msg).get("status") == "completed":
                break
    finally:
        listeners[job_id].remove(q)
