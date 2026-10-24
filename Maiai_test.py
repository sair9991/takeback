import chess
import chess.engine

eng = chess.engine.SimpleEngine.popen_uci([
    "maia3-uci", "--model", "maia3-5m", "--use-uci-history",
])

def ask_color():
    while True:
        choice = input("Your color (white/black): ").strip().lower()
        if choice in ("w", "white"):
            return chess.WHITE
        if choice in ("b", "black"):
            return chess.BLACK
        print("Enter white or black.")

def ask_elo():
    print("Elo examples: 1000, 1500, 2000. Any integer from 0 to 5000 works, such as 1642.")
    while True:
        raw = input("Your Elo: ").strip()
        try:
            elo = int(raw)
        except ValueError:
            print("Enter a whole number.")
            continue
        if 0 <= elo <= 5000:
            return elo
        print("Elo must be from 0 to 5000.")

def show_board(board):
    print(board)
    print()

def maia_move(board):
    move = eng.play(board, chess.engine.Limit(nodes=1)).move
    san = board.san(move)
    board.push(move)
    print(f"Maia plays {san}")
    show_board(board)

try:
    user_color = ask_color()
    elo = ask_elo()
    eng.configure({"Elo": elo})

    board = chess.Board()
    show_board(board)

    if user_color == chess.BLACK and not board.is_game_over():
        maia_move(board)

    while not board.is_game_over():
        raw = input("Your move (or quit): ").strip()
        if raw.lower() in ("quit", "q", "exit"):
            break
        try:
            board.push_san(raw)
        except ValueError:
            print("Illegal move. Use chess notation such as e4, Nf3, or O-O.")
            continue

        if board.is_game_over():
            show_board(board)
            print(f"Game over: {board.result()}")
            break

        maia_move(board)
        if board.is_game_over():
            print(f"Game over: {board.result()}")
finally:
    eng.close()
