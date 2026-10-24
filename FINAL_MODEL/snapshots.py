
"""
snapshots.py - Turn the games CSV into per-move training snapshots.

Input CSV columns (one game per row):
    player_id, date, player_color, time_control, player_elo,
    opponent, opponent_elo, result, moves
where `moves` is PGN movetext with a clock comment after every move, e.g.
    1. e4 {[%clk 0:09:58.8]} 1... c6 {[%clk 0:09:37.3]} 2. d4 {[%clk 0:09:57.2]} ...

Output: one snapshot per move made by the target player. Each snapshot is the
board state JUST BEFORE that move, plus the labels (move played, seconds spent)
and context (clocks, opponent's last move and think time, ratings).

Usage:
    python snapshots.py games.csv --out snapshots.csv [--player NAME]
Requires: pip install python-chess
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, asdict, fields
from typing import Optional

import chess
import chess.pgn

REQUIRED_COLUMNS = {
    "player_id", "date", "player_color", "time_control",
    "player_elo", "opponent", "opponent_elo", "result", "moves",
}
MIN_THINK_S = 0.1        # floor before taking the log (clocks have 0.1 s resolution)
CLOCK_TOLERANCE_S = 0.15  # allowed rounding slack when checking clocks never go up

# [%clk H:MM:SS(.s)] or [%clk M:SS(.s)]
CLK_RE = re.compile(r"\[%clk\s+(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\]")


class DropGame(Exception):
    """Raised when a game fails a cleaning rule. `reason` is a short code."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


# --------------------------------------------------------------------------- #
# Small parsers
# --------------------------------------------------------------------------- #
def parse_clock(comment: str) -> Optional[float]:
    """'{[%clk 0:09:58.8]}' comment text -> seconds left (598.8), or None."""
    m = CLK_RE.search(comment or "")
    if not m:
        return None
    hours = int(m.group(1) or 0)
    return round(hours * 3600 + int(m.group(2)) * 60 + float(m.group(3)), 3)


def parse_time_control(tc) -> tuple[float, float]:
    """'600' -> (600, 0); '180+2' -> (180, 2). Daily ('1/86400') is rejected."""
    s = str(tc).strip()
    if "/" in s:
        raise DropGame("bad_time_control", f"daily/correspondence: {s!r}")
    try:
        base, _, inc = s.partition("+")
        return float(base), float(inc or 0)
    except ValueError:
        raise DropGame("bad_time_control", repr(s))


def _to_int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        raise DropGame("bad_elo", repr(value))


# --------------------------------------------------------------------------- #
# Step 1: movetext -> plies (ply, side, move, clock left after, in seconds)
# --------------------------------------------------------------------------- #
@dataclass
class PlyRecord:
    ply: int                      # 1 = White's first move
    side: str                     # 'white' | 'black'
    san: str
    uci: str
    fen_before: str               # board state before this move
    n_legal: int                  # number of legal moves in fen_before
    clock_after: Optional[float]  # seconds left on mover's clock after the move
    clock_before: Optional[float] = None
    seconds_spent: Optional[float] = None


def parse_moves(movetext: str) -> list[PlyRecord]:
    """Replay the movetext and return one PlyRecord per ply."""
    game = chess.pgn.read_game(io.StringIO(movetext or ""))
    if game is None:
        raise DropGame("unparseable_moves", "empty movetext")
    if game.errors:
        raise DropGame("unparseable_moves", str(game.errors[0]))

    board = game.board()
    plies: list[PlyRecord] = []
    for ply, node in enumerate(game.mainline(), start=1):
        plies.append(PlyRecord(
            ply=ply,
            side="white" if board.turn == chess.WHITE else "black",
            san=board.san(node.move),
            uci=node.move.uci(),
            fen_before=board.fen(),
            n_legal=board.legal_moves.count(),
            clock_after=parse_clock(node.comment),
        ))
        board.push(node.move)
    if not plies:
        raise DropGame("unparseable_moves", "no moves")
    return plies


# --------------------------------------------------------------------------- #
# Step 2: think times for BOTH sides
# --------------------------------------------------------------------------- #
def attach_think_times(plies: list[PlyRecord], base: float, inc: float) -> None:
    """
    Fill clock_before and seconds_spent for every ply (both players).

        clock_before  = the mover's own clock after their previous move
                        (the starting clock for their first move)
        seconds_spent = clock_before - clock_after + increment
    """
    last_clock = {"white": base, "black": base}
    for p in plies:
        if p.clock_after is None:
            raise DropGame("missing_clocks", f"ply {p.ply}")
        p.clock_before = last_clock[p.side]
        p.seconds_spent = round(p.clock_before - p.clock_after + inc, 3)
        if p.seconds_spent < -CLOCK_TOLERANCE_S:
            raise DropGame("clock_increased",
                           f"ply {p.ply}: {p.clock_before} -> {p.clock_after} (inc {inc})")
        p.seconds_spent = max(p.seconds_spent, 0.0)
        last_clock[p.side] = p.clock_after


# --------------------------------------------------------------------------- #
# Step 3: snapshots
# --------------------------------------------------------------------------- #
@dataclass
class Snapshot:
    # identity / ordering
    game_id: str
    game_order: int               # row position in the CSV (tie-break for same-day games)
    player_id: str
    date: str
    player_color: str
    time_control: str
    base_seconds: float
    increment_seconds: float
    # position and move
    ply: int
    move_number: int              # full-move number: 1 for plies 1-2, 2 for plies 3-4, ...
    board_fen: str                # board BEFORE the player's move (pieces, side, castling, ep)
    n_legal_moves: int
    move_san: str                 # label 1: move played
    move_uci: str
    # time
    seconds_spent: float          # label 2 (raw seconds)
    log_seconds: float            # ln(max(seconds_spent, 0.1))
    time_label_valid: bool        # False for each side's first move (start-of-game delay)
    clock_before: float
    clock_after: float
    # opponent context
    opp_last_move_san: Optional[str]    # None if the player moves first (ply 1)
    opp_last_think_s: Optional[float]
    opp_clock: float                    # opponent's clock when the player is to move
    # ratings / outcome
    player_elo: int
    opponent_elo: int
    opponent: str
    result: str


def make_game_id(row: dict) -> str:
    key = "|".join(str(row.get(k, "")).strip() for k in
                   ("player_id", "date", "player_color", "opponent", "moves"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def build_game_snapshots(row: dict, game_order: int = 0) -> list[Snapshot]:
    """One CSV row -> snapshots for the target player's moves. Raises DropGame."""
    color = str(row["player_color"]).strip().lower()
    if color not in ("white", "black"):
        raise DropGame("bad_color", repr(row["player_color"]))

    base, inc = parse_time_control(row["time_control"])
    player_elo, opp_elo = _to_int(row["player_elo"]), _to_int(row["opponent_elo"])

    plies = parse_moves(row["moves"])
    attach_think_times(plies, base, inc)

    game_id = make_game_id(row)
    snaps: list[Snapshot] = []
    for i, p in enumerate(plies):
        if p.side != color:
            continue
        prev = plies[i - 1] if i > 0 else None    # opponent's most recent move
        snaps.append(Snapshot(
            game_id=game_id, game_order=game_order,
            player_id=str(row["player_id"]).strip(), date=str(row["date"]).strip(),
            player_color=color, time_control=str(row["time_control"]).strip(),
            base_seconds=base, increment_seconds=inc,
            ply=p.ply, move_number=(p.ply + 1) // 2,
            board_fen=p.fen_before, n_legal_moves=p.n_legal,
            move_san=p.san, move_uci=p.uci,
            seconds_spent=p.seconds_spent,
            log_seconds=round(math.log(max(p.seconds_spent, MIN_THINK_S)), 4),
            time_label_valid=p.ply > 2,
            clock_before=p.clock_before, clock_after=p.clock_after,
            opp_last_move_san=prev.san if prev else None,
            opp_last_think_s=prev.seconds_spent if prev else None,
            opp_clock=prev.clock_after if prev else base,
            player_elo=player_elo, opponent_elo=opp_elo,
            opponent=str(row["opponent"]).strip(), result=str(row["result"]).strip(),
        ))
    return snaps


# --------------------------------------------------------------------------- #
# Step 4: whole file
# --------------------------------------------------------------------------- #
def load_rows(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            sys.exit(f"CSV is missing columns: {sorted(missing)}")
        return [r for r in reader if any((v or "").strip() for v in r.values())]


def build_snapshot_table(rows: list[dict], player_id: Optional[str] = None):
    """Returns (snapshots, report). `report` counts kept games and drop reasons."""
    report: Counter = Counter()
    seen: set[str] = set()
    snapshots: list[Snapshot] = []
    for order, row in enumerate(rows):
        if player_id and str(row["player_id"]).strip().lower() != player_id.lower():
            report["skipped_other_player"] += 1
            continue
        try:
            gid = make_game_id(row)
            if gid in seen:
                raise DropGame("duplicate")
            snaps = build_game_snapshots(row, order)
            seen.add(gid)
            snapshots.extend(snaps)
            report["kept"] += 1
        except DropGame as e:
            report[f"dropped_{e.reason}"] += 1
    return snapshots, report


def write_csv(snapshots: list[Snapshot], path: str) -> None:
    cols = [f.name for f in fields(Snapshot)]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for s in snapshots:
            w.writerow({k: ("" if v is None else v) for k, v in asdict(s).items()})


def run(csv_path, out="snapshots.csv", player=None):
    rows = load_rows(csv_path)
    snaps, report = build_snapshot_table(rows, player)
    write_csv(snaps, out)
    print(f"rows read: {len(rows)}")
    for k, v in sorted(report.items()):
        print(f"  {k}: {v}")
    kept = report["kept"]
    print(f"snapshots: {len(snaps)}" + (f" (~{len(snaps) / kept:.1f} per game)" if kept else ""))
    print(f"wrote {out}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_path")
    ap.add_argument("--out", default="snapshots.csv")
    ap.add_argument("--player", help="only build snapshots for this player_id")
    args = ap.parse_args()
    run(args.csv_path, args.out, args.player)


if __name__ == "__main__":
    main()