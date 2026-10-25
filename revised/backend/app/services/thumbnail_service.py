from functools import lru_cache
from typing import List, Optional

try:
    import chess
    import chess.svg
except ImportError:
    chess = None


@lru_cache(maxsize=1024)
def generate_board_svg(
    moves_tuple: tuple[str, ...],
    player_color: str,
    target_ply: int,
) -> str:
    """Generates an SVG board representation with in-memory caching."""
    if chess is None:
        raise RuntimeError("python-chess is not installed")

    board = chess.Board()
    for move in moves_tuple[:target_ply]:
        try:
            board.push_san(move)
        except Exception:
            break

    orientation = chess.WHITE if player_color.lower() == "white" else chess.BLACK
    return chess.svg.board(
        board=board,
        orientation=orientation,
        size=300,
        coordinates=False,
        colors={"square light": "#f0d9b5", "square dark": "#b58863"},
    )


def get_thumbnail_svg(game_id: str, moves: List[str], player_color: str, ply: Optional[int] = None) -> str:
    if ply is not None:
        target_ply = min(max(0, ply), len(moves))
    else:
        seed = sum(ord(c) for c in str(game_id))
        min_ply = min(10, len(moves))
        max_ply = min(26, len(moves))
        target_ply = min_ply + (seed % (max(1, max_ply - min_ply + 1)))

    moves_tuple = tuple(moves)
    return generate_board_svg(moves_tuple, player_color, target_ply)
