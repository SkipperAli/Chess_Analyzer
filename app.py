from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import chess
import chess.engine
import chess.pgn
import os
import urllib.request
import urllib.parse
import json as json_lib
import io

app = Flask(__name__, static_folder='static')
CORS(app)

STOCKFISH_PATH = os.environ.get(
    'STOCKFISH_PATH',
    r'stockfish\stockfish-windows-x86-64-avx2.exe'
)

ANALYSIS_DEPTH = 16
PGN_ANALYSIS_DEPTH = 12
MULTIPV = 3

PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0
}

# Difficulty level → (Skill Level 0-20, ELO approx, think_time_ms)
# Skill Level 0 = ~800 ELO, scale up to 20 = ~3200
DIFFICULTY_MAP = {
    1:  (0,  800,  50),
    2:  (1,  900,  50),
    3:  (2, 1000,  80),
    4:  (3, 1100,  80),
    5:  (4, 1200, 100),
    6:  (5, 1300, 100),
    7:  (6, 1400, 150),
    8:  (7, 1500, 150),
    9:  (8, 1600, 200),
    10: (9, 1700, 200),
    11: (10,1800, 250),
    12: (11,1900, 300),
    13: (12,2000, 350),
    14: (13,2100, 400),
    15: (14,2200, 500),
    16: (15,2300, 600),
    17: (16,2500, 700),
    18: (17,2700, 800),
    19: (18,2900, 900),
    20: (20,3200,1000),
}

def get_engine():
    try:
        return chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    except:
        return None

def white_eval(pov_score):
    """Engine score -> pawns from White's point of view. Mate ~ +/-100."""
    return pov_score.white().score(mate_score=10000) / 100.0

def is_real_sacrifice(board_before, move):
    """
    True only if:
    1. The moving piece lands on a square where an opponent piece of LOWER value can recapture,
       OR the moving piece captures a piece of lower value AND can be recaptured.
    We require actual material imbalance, not just moving to an attacked square.
    """
    piece = board_before.piece_at(move.from_square)
    captured = board_before.piece_at(move.to_square)

    if piece is None:
        return False

    mover_val = PIECE_VALUES.get(piece.piece_type, 0)

    # Case 1: captures a less-valuable piece and can be recaptured
    if captured is not None:
        cap_val = PIECE_VALUES.get(captured.piece_type, 0)
        if mover_val > cap_val:
            # moving piece is worth more than what it captures → real sacrifice
            board_copy = board_before.copy()
            board_copy.push(move)
            recapturers = board_copy.attackers(not board_before.turn, move.to_square)
            if recapturers:
                return True

    # Case 2: quiet move to a square attacked by lower-value piece (e.g. Rook to square attacked by pawn)
    if captured is None and mover_val >= 3:
        board_copy = board_before.copy()
        board_copy.push(move)
        attackers = list(board_copy.attackers(not board_before.turn, move.to_square))
        if attackers:
            min_attacker_val = min(
                PIECE_VALUES.get(board_copy.piece_at(sq).piece_type, 0)
                for sq in attackers
                if board_copy.piece_at(sq)
            )
            if min_attacker_val < mover_val:
                return True

    return False


def classify_move(before_eval, after_eval, is_white_turn, best_move_uci, played_uci,
                  board_before, move, top_moves_uci=None):
    """
    Brilliant (!!): Real material sacrifice that is the BEST move (exact top choice).
    Great (!):      The ONLY best move in the position (very high loss threshold — a critical move
                    where other moves lose significantly more).
    Best (★):       Exact engine top choice (not a sacrifice, not uniquely forced).
    Inaccuracy (?): small eval drop < 0.5
    Mistake (??):   eval drop 0.5 – 2.0
    Blunder (???):  eval drop > 2.0
    """
    if is_white_turn:
        loss = -(after_eval - before_eval)
    else:
        loss = -(before_eval - after_eval)
    if loss < 0:
        loss = 0

    is_best = played_uci == best_move_uci

    # ── BRILLIANT: must be exact best move AND a real sacrifice
    if is_best and is_real_sacrifice(board_before, move):
        return 'brilliant'

    # ── BEST: exact engine top choice (no sacrifice involved)
    if is_best:
        return 'best'

    # ── GREAT: played move is very close to best (loss < 0.15),
    #           but ONLY if the second-best alternative was significantly worse.
    #           top_moves_uci[1] exists and its eval is much lower → only move.
    if loss < 0.15 and top_moves_uci and len(top_moves_uci) >= 2:
        # second_loss = how much worse 2nd best is compared to best
        # We already have before_eval = eval of best move
        # We need eval of 2nd best to judge uniqueness — passed as top_moves_uci list of (uci, eval)
        if isinstance(top_moves_uci[0], tuple):
            best_eval_val = top_moves_uci[0][1]
            second_eval_val = top_moves_uci[1][1]
            gap = abs(best_eval_val - second_eval_val)
            if gap >= 0.5:
                return 'great'
        else:
            # fallback: just label as great if very close to best
            return 'great'

    elif loss < 0.15:
        # Close to best but can't verify uniqueness → still great
        return 'great'

    # ── INACCURACY
    if loss < 0.5:
        return 'inaccuracy'

    # ── MISTAKE
    if loss < 2.0:
        return 'mistake'

    # ── BLUNDER
    return 'blunder'


@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/analyze', methods=['POST'])
def analyze_move():
    data = request.json
    fen_before = data.get('fen_before')
    move_uci = data.get('move')
    fen_after = data.get('fen_after')

    if not all([fen_before, move_uci, fen_after]):
        return jsonify({'error': 'Missing fields'}), 400

    engine = get_engine()
    if not engine:
        return jsonify({'error': f'Stockfish not found at {STOCKFISH_PATH}'}), 500

    try:
        board_before = chess.Board(fen_before)
        board_after = chess.Board(fen_after)
        move = chess.Move.from_uci(move_uci)
        is_white_turn = board_before.turn == chess.WHITE

        info_before = engine.analyse(board_before, chess.engine.Limit(depth=ANALYSIS_DEPTH), multipv=MULTIPV)
        best_info = info_before[0]
        best_move_uci = best_info['pv'][0].uci() if 'pv' in best_info else move_uci
        best_eval_white = white_eval(best_info['score'])

        info_after = engine.analyse(board_after, chess.engine.Limit(depth=ANALYSIS_DEPTH))
        after_eval_white = white_eval(info_after['score'])

        # Build top moves list as (uci, eval_white) for great-move detection
        top_moves = []
        for alt_info in info_before[:MULTIPV]:
            if 'pv' in alt_info:
                alt_uci = alt_info['pv'][0].uci()
                top_moves.append((alt_uci, white_eval(alt_info['score'])))

        classification = classify_move(
            best_eval_white, after_eval_white, is_white_turn,
            best_move_uci, move_uci, board_before, move,
            top_moves_uci=top_moves
        )

        alternatives = [{'move': m, 'eval': round(e, 2)} for m, e in top_moves]

        engine.quit()
        return jsonify({
            'classification': classification,
            'eval_before': round(best_eval_white, 2),
            'eval_after': round(after_eval_white, 2),
            'best_move': best_move_uci,
            'played_move': move_uci,
            'alternatives': alternatives,
            'is_best': move_uci == best_move_uci,
            'player': 'white' if is_white_turn else 'black'
        })
    except Exception as e:
        try: engine.quit()
        except: pass
        return jsonify({'error': str(e)}), 500

@app.route('/api/stockfish-status', methods=['GET'])
def stockfish_status():
    engine = get_engine()
    if engine:
        engine.quit()
        return jsonify({'ok': True, 'path': STOCKFISH_PATH})
    return jsonify({'ok': False, 'path': STOCKFISH_PATH})

@app.route('/api/hint', methods=['POST'])
def get_hint():
    data = request.json
    fen = data.get('fen')
    if not fen:
        return jsonify({'error': 'Missing FEN'}), 400
    engine = get_engine()
    if not engine:
        return jsonify({'error': 'Stockfish not found'}), 500
    try:
        board = chess.Board(fen)
        info = engine.analyse(board, chess.engine.Limit(depth=ANALYSIS_DEPTH), multipv=3)
        hints = []
        for i in info:
            if 'pv' in i:
                move_uci = i['pv'][0].uci()
                san = board.san(chess.Move.from_uci(move_uci))
                hints.append({
                    'move': move_uci,
                    'san': san,
                    'eval': round(white_eval(i['score']), 2)
                })
        engine.quit()
        return jsonify({'hints': hints})
    except Exception as e:
        try: engine.quit()
        except: pass
        return jsonify({'error': str(e)}), 500

@app.route('/api/next_best', methods=['POST'])
def get_next_best():
    """Next-Move Calculator: return top 3 moves for current position."""
    data = request.json
    fen = data.get('fen')
    if not fen:
        return jsonify({'error': 'Missing FEN'}), 400
    engine = get_engine()
    if not engine:
        return jsonify({'error': 'Stockfish not found'}), 500
    try:
        board = chess.Board(fen)
        info = engine.analyse(board, chess.engine.Limit(depth=ANALYSIS_DEPTH), multipv=3)
        moves = []
        for i in info:
            if 'pv' in i:
                move_uci = i['pv'][0].uci()
                san = board.san(chess.Move.from_uci(move_uci))
                eval_val = white_eval(i['score'])
                moves.append({'move': move_uci, 'san': san, 'eval': round(eval_val, 2)})
        engine.quit()
        return jsonify({'moves': moves})
    except Exception as e:
        try: engine.quit()
        except: pass
        return jsonify({'error': str(e)}), 500

@app.route('/api/next_best_pgn', methods=['POST'])
def next_best_pgn():
    """
    PGN paste for Next-Move Calculator mode.
    Loads PGN moves WITHOUT analysis, just replays position.
    Returns move list (san, uci, fen_after) so frontend can navigate,
    then user clicks Analyze to get best moves for current position.
    """
    data = request.json
    pgn_text = data.get('pgn', '').strip()
    if not pgn_text:
        return jsonify({'error': 'Empty PGN'}), 400

    try:
        game_pgn = chess.pgn.read_game(io.StringIO(pgn_text))
        if not game_pgn:
            return jsonify({'error': 'Invalid PGN'}), 400

        board = game_pgn.board()
        moves = []

        for move in game_pgn.mainline_moves():
            san = board.san(move)
            board.push(move)
            moves.append({
                'uci': move.uci(),
                'san': san,
                'fen_after': board.fen(),
                'color': 'w' if board.turn == chess.BLACK else 'b',  # color that JUST moved
            })

        return jsonify({
            'moves': moves,
            'headers': dict(game_pgn.headers),
            'final_fen': board.fen()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/bot_move', methods=['POST'])
def get_bot_move():
    """
    Play vs Bot with proper ELO-mapped difficulty.
    difficulty: 1-20 → mapped to Skill Level + think time
    """
    data = request.json
    fen = data.get('fen')
    difficulty = max(1, min(20, int(data.get('difficulty', 10))))

    if not fen:
        return jsonify({'error': 'Missing FEN'}), 400

    engine = get_engine()
    if not engine:
        return jsonify({'error': 'Stockfish not found'}), 500

    try:
        board = chess.Board(fen)
        if board.is_game_over():
            engine.quit()
            return jsonify({'error': 'Game is over'}), 400

        skill_level, elo_approx, think_ms = DIFFICULTY_MAP[difficulty]
        think_time = think_ms / 1000.0

        engine.configure({'Skill Level': skill_level})
        result = engine.play(board, chess.engine.Limit(time=think_time))
        move = result.move
        san = board.san(move)
        board.push(move)

        # Quick eval
        info = engine.analyse(board, chess.engine.Limit(depth=8))
        eval_after = white_eval(info['score'])

        game_over = board.is_game_over()
        outcome = None
        if game_over:
            res = board.outcome()
            if res:
                if res.winner is True:
                    outcome = 'white'
                elif res.winner is False:
                    outcome = 'black'
                else:
                    outcome = 'draw'

        engine.quit()
        return jsonify({
            'move': move.uci(),
            'san': san,
            'eval': round(eval_after, 2),
            'fen_after': board.fen(),
            'game_over': game_over,
            'outcome': outcome,
            'elo': elo_approx
        })
    except Exception as e:
        try: engine.quit()
        except: pass
        return jsonify({'error': str(e)}), 500

@app.route('/api/book', methods=['POST'])
def get_book_moves():
    data = request.json
    fen = data.get('fen')
    if not fen:
        return jsonify({'error': 'Missing FEN'}), 400
    try:
        encoded = urllib.parse.quote(fen)
        url = f'https://explorer.lichess.ovh/lichess?fen={encoded}&topGames=0&recentGames=0'
        req = urllib.request.Request(url, headers={'User-Agent': 'ChessAnalyzer/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode()
        d = json_lib.loads(raw)
        moves = []
        for m in d.get('moves', []):
            total = m['white'] + m['black'] + m['draws']
            if total == 0:
                continue
            moves.append({
                'uci': m['uci'],
                'san': m['san'],
                'total': total,
                'white_pct': round(m['white'] / total * 100),
                'draw_pct':  round(m['draws'] / total * 100),
                'black_pct': round(m['black'] / total * 100),
            })
        return jsonify({'moves': moves, 'opening': d.get('opening')})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analyze_pgn', methods=['POST'])
def analyze_pgn():
    data = request.json
    pgn_text = data.get('pgn', '').strip()
    if not pgn_text:
        return jsonify({'error': 'Empty PGN'}), 400

    engine = get_engine()
    if not engine:
        return jsonify({'error': f'Stockfish not found at {STOCKFISH_PATH}'}), 500

    try:
        game_pgn = chess.pgn.read_game(io.StringIO(pgn_text))
        if not game_pgn:
            engine.quit()
            return jsonify({'error': 'Invalid PGN'}), 400

        board = game_pgn.board()
        results = []
        limit = chess.engine.Limit(depth=PGN_ANALYSIS_DEPTH)

        for move in game_pgn.mainline_moves():
            fen_before = board.fen()
            is_white = board.turn == chess.WHITE
            san = board.san(move)
            board_before_copy = board.copy()

            info_before = engine.analyse(board, limit, multipv=MULTIPV)
            best_info = info_before[0]
            best_move_uci = best_info['pv'][0].uci() if 'pv' in best_info else move.uci()
            best_eval_white = white_eval(best_info['score'])

            # Build top moves for great detection
            top_moves = []
            for alt in info_before[:MULTIPV]:
                if 'pv' in alt:
                    alt_uci = alt['pv'][0].uci()
                    top_moves.append((alt_uci, white_eval(alt['score'])))

            board.push(move)

            info_after = engine.analyse(board, limit)
            after_eval_white = white_eval(info_after['score'])

            classification = classify_move(
                best_eval_white, after_eval_white, is_white,
                best_move_uci, move.uci(), board_before_copy, move,
                top_moves_uci=top_moves
            )

            alternatives = [{'move': m, 'eval': round(e, 2)} for m, e in top_moves]

            results.append({
                'uci': move.uci(),
                'san': san,
                'fen_before': fen_before,
                'fen_after': board.fen(),
                'classification': classification,
                'eval_before': round(best_eval_white, 2),
                'eval_after': round(after_eval_white, 2),
                'best_move': best_move_uci,
                'is_best': move.uci() == best_move_uci,
                'alternatives': alternatives,
                'player': 'white' if is_white else 'black',
                'color': 'w' if is_white else 'b',
            })

        engine.quit()
        return jsonify({'moves': results, 'headers': dict(game_pgn.headers)})

    except Exception as e:
        try: engine.quit()
        except: pass
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print(f"Stockfish path: {STOCKFISH_PATH}")
    print("Starting Chess Analyzer on http://localhost:5000")
    app.run(debug=True, port=5000)
