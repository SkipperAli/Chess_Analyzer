# Chess Analyzer

Real-time chess move analyzer powered by Stockfish. Classifies every move as:
**Brilliant ✨ · Best ★ · Great ▲ · Good ● · Inaccuracy ?! · Miss ? · Blunder ??**

---

## Setup (Windows)

### 1. Install Python dependencies
```
pip install flask flask-cors chess
```

### 2. Download Stockfish
- Go to https://stockfishchess.org/download/
- Download the Windows version
- Extract it into a `stockfish` folder next to `app.py`, so the exe is at:
  `stockfish\stockfish-windows-x86-64-avx2.exe` (the default the app looks for)
- **OR** set the env variable before running:
  ```
  set STOCKFISH_PATH=C:\Users\YourName\Downloads\stockfish\stockfish.exe
  ```

### 3. Run the app
Double-click `start.bat`  
OR run manually:
```
python app.py
```

### 4. Open browser
Go to: http://localhost:5000

---

## How to Play

**Click or drag:** Click a piece to see valid moves, then click the destination — or drag it. Works with touch too.

**Branching:** Step back with ◀ / arrow keys and play a different move to continue from there (later moves are discarded after a confirm).

**No Stockfish?** The board, move list, navigation and PGN loading still work; analysis, hints and the bot need the engine.

**Type moves:** Use the text box at the bottom. Accepts:
- UCI format: `e2e4`, `g1f3`, `e7e8q` (promotion)
- SAN format: `e4`, `Nf3`, `O-O`, `O-O-O`

**Controls:**
- **↩ Undo** — take back last move
- **⇅ Flip** — flip board perspective  
- **💡 Hint** — show Stockfish's top 3 suggestions
- **✕ New Game** — reset board

---

## Move Classifications

| Label | Eval Loss | Meaning |
|-------|-----------|---------|
| Brilliant !! | 0 | Engine's top move that is also a material sacrifice |
| Best ★ | 0 | Engine's top move |
| Great ! | < 0.15 | Near-best when the alternatives are clearly worse |
| Inaccuracy ? | < 0.5 | Slightly suboptimal |
| Mistake ?? | 0.5 – 2.0 | Significant mistake |
| Blunder ??? | ≥ 2.0 | Major mistake |

All evals are shown from White's point of view (+ = White better, M3 = mate in 3).

---

## Files

```
chess_analyzer/
├── app.py          # Flask backend + Stockfish integration
├── requirements.txt
├── start.bat       # Windows launcher
├── README.md
└── static/
    ├── index.html  # Frontend chessboard UI
    ├── style.css   # Styles
    └── chess.js    # Move generation / validation (browser side)
```
