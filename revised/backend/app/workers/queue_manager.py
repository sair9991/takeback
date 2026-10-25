import asyncio
import json
import time
from typing import AsyncGenerator
from app.db.repositories import model_repo, analysis_repo
from app.services import evaluation_service, commentary_service, training_service

queue = asyncio.Queue()
jobs = {}
listeners = {}


def is_cached(opp: str) -> bool:
    path = model_repo.get_model_weights_path(opp)
    return path is not None and path.is_file()


async def broadcast(job_id: str, data: dict):
    if job_id in jobs:
        jobs[job_id].update(data)
    for q in listeners.get(job_id, []):
        await q.put(json.dumps(jobs.get(job_id, data)))


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
            await asyncio.to_thread(
                training_service.run_training_pipeline,
                opp,
                broadcast_progress,
                uid,
            )

            if uid and gid:
                try:
                    await asyncio.to_thread(evaluation_service.get_or_calculate_odds, gid, uid)
                    commentary_service.start_background_commentary_generation(gid, uid)
                except Exception as e:
                    print(f"[Worker] Error pre-caching analysis for {gid}: {e}")

            stats = model_repo.get_model_stats(opp)
            rating = stats.get("chess_elo") if stats else None
            await broadcast(
                job_id,
                {
                    "status": "completed",
                    "progress": 100,
                    "message": f"Model for {opp} cached and ready!",
                    "rating": rating,
                    "chess_elo": rating,
                    "val_accuracy": stats.get("val_accuracy") if stats else None,
                },
            )
        except Exception as e:
            print(f"[Worker Error] {e}")
            await broadcast(job_id, {"status": "failed", "progress": 0, "message": str(e)})

        queue.task_done()


def enqueue(opp: str, uid: str, gid: str) -> str:
    job_id = f"train_{opp.lower()}_{int(time.time())}"
    jobs[job_id] = {"id": job_id, "opp": opp, "status": "queued", "progress": 0}
    listeners[job_id] = []
    queue.put_nowait({"id": job_id, "opp": opp, "uid": uid, "gid": gid})
    return job_id


async def stream(job_id: str) -> AsyncGenerator[str, None]:
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
        if job_id in listeners and q in listeners[job_id]:
            listeners[job_id].remove(q)
