import asyncio
import json
import time
from pathlib import Path
import evaluator
import gemma_service
import helper

ROOT = Path(__file__).resolve().parents[3]

queue = asyncio.Queue()
jobs = {}
listeners = {}


def is_cached(opp: str) -> bool:
    """Returns True ONLY if a record exists in models table AND the .pt file exists on disk."""
    row = helper.query_one("SELECT weights_path FROM models WHERE LOWER(player_id) = LOWER(?)", (opp,))
    if not row or not row.get("weights_path"):
        return False
    path = Path(row["weights_path"])
    if not path.is_absolute():
        path = ROOT / path
    return path.is_file()


async def broadcast(job_id: str, data: dict):
    jobs[job_id].update(data)
    for q in listeners.get(job_id, []):
        await q.put(json.dumps(jobs[job_id]))


async def worker():
    loop = asyncio.get_running_loop()
    while True:
        job = await queue.get()
        job_id, opp, uid, gid = job["id"], job["opp"], job["uid"], job["gid"]

        def broadcast_progress(step: str, pct: int, msg: str):
            asyncio.run_coroutine_threadsafe(
                broadcast(job_id, {"status": step, "progress": pct, "message": msg}),
                loop,
            )

        try:
            import training_service
            await asyncio.to_thread(
                training_service.run_training_pipeline,
                opp,
                broadcast_progress,
            )

            if uid and gid:
                try:
                    await asyncio.to_thread(evaluator.cache_game_odds, gid, uid)
                    await asyncio.to_thread(gemma_service.cache_game_commentary_and_narrative, gid, uid)
                except Exception as e:
                    print(f"Error caching analysis for {gid}: {e}")
                helper.execute("INSERT OR IGNORE INTO analyzed_games (user_id, game_id) VALUES (?, ?)", (uid, gid))

            await broadcast(job_id, {"status": "completed", "progress": 100, "message": f"Model for {opp} cached and ready!"})
        except Exception as e:
            print(f"[Training Worker Error] {e}")
            await broadcast(job_id, {"status": "failed", "progress": 0, "message": str(e)})

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
            status = json.loads(msg).get("status")
            if status in ("completed", "failed"):
                break
    finally:
        listeners[job_id].remove(q)
