<script lang="ts">
  import { onDestroy } from 'svelte';
  import { page } from '$app/state';
  import { Chess } from 'chess.js';
  import Chessboard from '../../../../lib/components/Chessboard.svelte';
  import { getDummyGames, type Game } from '../../../../lib/functions/games';

  const gameId = $derived(page.params.id);

  // Retrieve current game or fallback
  const allGames = getDummyGames();
  const currentGame = $derived(
    allGames.find((g) => g.id === gameId) || {
      id: gameId || '1',
      opponent: 'Opponent Name',
      date: 'January 1st, 2026',
      platform: 'Chess.com'
    }
  );

  // Chess game logic using chess.js
  let chess = new Chess();
  let currentFen = $state(chess.fen());
  let moveHistory = $state<string[]>([]);

  // View mode: 'expanded' (controls, odds, clock, chat) vs 'focused' (players, ratings)
  let viewMode = $state<'expanded' | 'focused'>('expanded');

  // Complete classic sample game for replay: Paul Morphy's Opera Game (33 plies, finishes with checkmate)
  const samplePgnMoves = [
    'e4', 'e5',
    'Nf3', 'd6',
    'd4', 'Bg4',
    'dxe5', 'Bxf3',
    'Qxf3', 'dxe5',
    'Bc4', 'Nf6',
    'Qb3', 'Qe7',
    'Nc3', 'c6',
    'Bg5', 'b5',
    'Nxb5', 'cxb5',
    'Bxb5+', 'Nbd7',
    'O-O-O', 'Rd8',
    'Rxd7', 'Rxd7',
    'Rd1', 'Qe6',
    'Bxd7+', 'Nxd7',
    'Qb8+', 'Nxb8',
    'Rd8#'
  ];

  // Dynamic evaluation odds progression (starts at 50/50, ends at 100/0 checkmate)
  const evaluationOdds = [
    50, 50,
    52, 51,
    54, 53,
    57, 55,
    60, 58,
    65, 62,
    69, 66,
    73, 70,
    76, 73,
    80, 77,
    84, 82,
    88, 85,
    91, 89,
    94, 92,
    96, 95,
    98, 97,
    100
  ];

  let currentMoveIndex = $state(-1);
  let isPlaying = $state(false);
  let playInterval: ReturnType<typeof setInterval> | null = null;

  // Active odds
  let yourOdds = $derived(
    currentMoveIndex >= 0 && currentMoveIndex < evaluationOdds.length
      ? evaluationOdds[currentMoveIndex]
      : 50
  );
  let theirOdds = $derived(100 - yourOdds);

  // Active moves for You and Them
  let activeWhiteMove = $derived.by(() => {
    if (currentMoveIndex < 0) return '—';
    const lastWhiteIndex = currentMoveIndex % 2 === 0 ? currentMoveIndex : currentMoveIndex - 1;
    return samplePgnMoves[lastWhiteIndex] || '—';
  });

  let activeBlackMove = $derived.by(() => {
    if (currentMoveIndex < 1) return '—';
    const lastBlackIndex = currentMoveIndex % 2 === 1 ? currentMoveIndex : currentMoveIndex - 1;
    return samplePgnMoves[lastBlackIndex] || '—';
  });

  // Clocks calculated from moves made (simulating ticking game clocks)
  let youTime = $derived.by(() => {
    if (currentMoveIndex < 0) return 600;
    const whiteMovesCount = Math.floor((currentMoveIndex + 2) / 2);
    return Math.max(35, 600 - whiteMovesCount * 14);
  });

  let themTime = $derived.by(() => {
    if (currentMoveIndex < 1) return 600;
    const blackMovesCount = Math.floor((currentMoveIndex + 1) / 2);
    return Math.max(18, 600 - blackMovesCount * 16);
  });

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
  }

  // Game Commentary state (reactive based on current game ply)
  interface CommentaryMoment {
    phase: string;
    headline: string;
    text: string;
    isPivotal?: boolean;
    pivotalLabel?: string;
    pivotalId?: string;
  }

  let lastAcknowledgedPivotalId = $state<string | null>(null);
  let wasPausedForPivotal = $state(false);

  const gameCommentary = $derived.by<CommentaryMoment>(() => {
    if (currentMoveIndex < 0) {
      return {
        phase: 'Game Setup',
        headline: 'Opera Game: Morphy vs. Allies (1858)',
        text: "Paul Morphy takes White against Duke Karl of Brunswick and Count Isouard in Paris. White begins with classical King's Pawn development."
      };
    }
    const ply = currentMoveIndex;
    if (ply <= 1) {
      return {
        phase: 'Opening',
        headline: 'Open Game Initiative',
        text: "Both sides contest the center immediately with 1.e4 e5, fighting for central control and opening avenues for bishops and queens."
      };
    }
    if (ply <= 3) {
      return {
        phase: 'Opening',
        headline: 'Philidor Defense',
        text: "Black adopts the Philidor Defense (2...d6). While solid, it restricts Black's dark-squared bishop and concedes spatial freedom to White."
      };
    }
    if (ply <= 5) {
      return {
        phase: 'Opening',
        headline: 'Center Break & Early Pin',
        text: "Morphy strikes the center with 3.d4. Black attempts to pin the knight with 3...Bg4, but White prepares to seize tempo and open lines."
      };
    }
    if (ply <= 7) {
      return {
        phase: 'Opening',
        headline: 'Conceding the Bishop Pair',
        text: "Black surrenders the light-squared bishop (4...Bxf3 5.Qxf3). White regains the piece with queen centralization and opens diagonal attacking avenues."
      };
    }
    if (ply <= 9) {
      return {
        phase: 'Development',
        headline: 'Rapid White Mobilization',
        text: "With 5...dxe5, the center opens up. Morphy now has open diagonals for both bishops and a centralized queen ready to launch attacking threats."
      };
    }
    if (ply <= 11) {
      return {
        phase: 'Attack',
        headline: 'Pressure on f7',
        text: "Morphy plays 6.Bc4, taking aim at Black's sensitive f7 weak point. Black blocks with 6...Nf6, but White's tactical pressure is mounting."
      };
    }
    if (ply <= 13) {
      return {
        phase: 'Attack',
        headline: 'Dual Threats (f7 & b7)',
        text: "7.Qb3 creates simultaneous mating threats on f7 and material threats on b7. Black defends f7 with 7...Qe7, falling further behind in piece development."
      };
    }
    if (ply <= 15) {
      return {
        phase: 'Development',
        headline: 'Relentless Piece Mobilization',
        text: "Morphy develops 8.Nc3, ignoring the pawn grab on b7 to prioritize total piece mobilization. Black plays 8...c6 to blunt the diagonal."
      };
    }
    if (ply <= 17) {
      return {
        phase: 'Critical Moment',
        headline: 'The Pin & The Counter-Thrust',
        text: "Morphy pins Black's knight with 9.Bg5. Black lashes out with 9...b5? attempting to kick the bishop, but fatally neglects king safety in the center.",
        isPivotal: true,
        pivotalLabel: 'Blunder',
        pivotalId: 'move-9-blunder'
      };
    }
    if (ply <= 19) {
      return {
        phase: 'Positional Sacrifice',
        headline: '10.Nxb5! Stripping the King',
        text: "Brilliant knight sacrifice! Morphy trades a knight for two pawns with 10.Nxb5! cxb5 to blow open files directly toward Black's uncastled monarch.",
        isPivotal: true,
        pivotalLabel: 'Piece Sac',
        pivotalId: 'move-10-sacrifice'
      };
    }
    if (ply <= 21) {
      return {
        phase: 'Tactical Pin',
        headline: 'Paralysis on the d-file',
        text: "11.Bxb5+ delivers check and forces Black into an agonizing pin with 11...Nbd7. Black's pieces are immobilized and tripping over each other."
      };
    }
    if (ply <= 23) {
      return {
        phase: 'Attack',
        headline: 'Queenside Castling with Tempo',
        text: "Morphy castles queenside (0-0-0)! In classical chess, castling activates the rook directly onto the open d-file with crushing pressure against d7."
      };
    }
    if (ply <= 25) {
      return {
        phase: 'Exchange Sacrifice',
        headline: '13.Rxd7! Shattering the Defense',
        text: "Morphy gives up a rook for a knight to eliminate Black's key defender. Black is forced to recapture 13...Rxd7, remaining pinned and helpless.",
        isPivotal: true,
        pivotalLabel: 'Rook Sac',
        pivotalId: 'move-13-exchange'
      };
    }
    if (ply <= 27) {
      return {
        phase: 'Attack',
        headline: 'Complete Piece Harmony',
        text: "14.Rd1 brings White's last remaining piece into the assault. All of Morphy's active pieces are participating while Black's kingside pieces remain asleep."
      };
    }
    if (ply <= 29) {
      return {
        phase: 'Decisive Strike',
        headline: 'Defenders Eliminated',
        text: "15.Bxd7+ simplifies into an irresistible mating net. Black's knight recaptures on d7, leaving Black's king with zero escape squares."
      };
    }
    if (ply <= 31) {
      return {
        phase: 'Queen Sacrifice',
        headline: '16.Qb8+!! The Immortal Deflection',
        text: "A legendary queen sacrifice! Morphy plays 16.Qb8+!, forcing 16...Nxb8 and deflecting Black's knight from covering d8.",
        isPivotal: true,
        pivotalLabel: 'Queen Sac',
        pivotalId: 'move-16-queen-sac'
      };
    }
    return {
      phase: 'Checkmate',
      headline: '17.Rd8# Immortal Checkmate!',
      text: "Checkmate! The d-file rook delivers the fatal blow, protected by the bishop on g5. A masterpiece of development, tempo, and piece coordination.",
      isPivotal: true,
      pivotalLabel: 'Checkmate',
      pivotalId: 'move-17-checkmate'
    };
  });

  // Move handling
  function handleMove(move: { from: string; to: string; san: string }) {
    chess.move(move.san);
    currentFen = chess.fen();
    moveHistory = chess.history();
    currentMoveIndex = moveHistory.length - 1;
  }

  // Controls mode: 'buttons' (play, forward, backward) vs 'slider' (scrubber)
  let controlsMode = $state<'buttons' | 'slider'>('buttons');

  function toggleControlsMode() {
    controlsMode = controlsMode === 'buttons' ? 'slider' : 'buttons';
  }

  function handleScrubberInput(e: Event) {
    stopAutoPlay();
    wasPausedForPivotal = false;
    const target = e.currentTarget as HTMLInputElement;
    const newIndex = parseInt(target.value, 10);
    jumpToMove(newIndex);
  }

  // Navigation controls
  function stepBackward() {
    stopAutoPlay();
    wasPausedForPivotal = false;
    if (currentMoveIndex >= 0) {
      currentMoveIndex--;
      reconstructFenToIndex(currentMoveIndex);
      if (!gameCommentary.isPivotal) {
        lastAcknowledgedPivotalId = null;
      }
    }
  }

  function stepForward() {
    stopAutoPlay();
    wasPausedForPivotal = false;
    if (currentMoveIndex < samplePgnMoves.length - 1) {
      currentMoveIndex++;
      reconstructFenToIndex(currentMoveIndex);
    }
  }

  function toggleAutoPlay() {
    if (isPlaying) {
      stopAutoPlay();
      wasPausedForPivotal = false;
    } else {
      // If we are at the end, restart from the beginning
      if (currentMoveIndex >= samplePgnMoves.length - 1) {
        currentMoveIndex = -1;
        reconstructFenToIndex(currentMoveIndex);
        lastAcknowledgedPivotalId = null;
        wasPausedForPivotal = false;
      }
      // If resuming from a pivotal moment, acknowledge it so autoplay continues
      if (gameCommentary.isPivotal && gameCommentary.pivotalId) {
        lastAcknowledgedPivotalId = gameCommentary.pivotalId;
      }
      wasPausedForPivotal = false;
      isPlaying = true;
      playInterval = setInterval(() => {
        if (currentMoveIndex < samplePgnMoves.length - 1) {
          currentMoveIndex++;
          reconstructFenToIndex(currentMoveIndex);

          // Auto-pause when arriving at a new pivotal moment
          if (
            gameCommentary.isPivotal &&
            gameCommentary.pivotalId &&
            gameCommentary.pivotalId !== lastAcknowledgedPivotalId
          ) {
            lastAcknowledgedPivotalId = gameCommentary.pivotalId;
            wasPausedForPivotal = true;
            stopAutoPlay();
          }
        } else {
          stopAutoPlay();
        }
      }, 1100);
    }
  }

  function stopAutoPlay() {
    isPlaying = false;
    if (playInterval) {
      clearInterval(playInterval);
      playInterval = null;
    }
  }

  function reconstructFenToIndex(targetIndex: number) {
    chess.reset();
    for (let i = 0; i <= targetIndex; i++) {
      if (samplePgnMoves[i]) {
        try {
          chess.move(samplePgnMoves[i]);
        } catch {
          break;
        }
      }
    }
    currentFen = chess.fen();
    moveHistory = chess.history();
  }

  function restartGame() {
    stopAutoPlay();
    wasPausedForPivotal = false;
    lastAcknowledgedPivotalId = null;
    chess.reset();
    currentFen = chess.fen();
    moveHistory = [];
    currentMoveIndex = -1;
  }

  // Moves Modal state and logic
  let showMovesModal = $state(false);
  let movesModalTab = $state<'played' | 'all'>('played');

  function jumpToMove(targetIndex: number) {
    stopAutoPlay();
    wasPausedForPivotal = false;
    currentMoveIndex = targetIndex;
    reconstructFenToIndex(currentMoveIndex);
    if (!gameCommentary.isPivotal) {
      lastAcknowledgedPivotalId = null;
    }
  }

  interface MovePair {
    moveNumber: number;
    whiteSan: string;
    whiteIndex: number;
    blackSan?: string;
    blackIndex?: number;
  }

  const allMovePairs = $derived.by(() => {
    const pairs: MovePair[] = [];
    for (let i = 0; i < samplePgnMoves.length; i += 2) {
      const moveNum = Math.floor(i / 2) + 1;
      pairs.push({
        moveNumber: moveNum,
        whiteSan: samplePgnMoves[i],
        whiteIndex: i,
        blackSan: samplePgnMoves[i + 1],
        blackIndex: samplePgnMoves[i + 1] ? i + 1 : undefined
      });
    }
    return pairs;
  });

  const displayedMovePairs = $derived.by(() => {
    if (movesModalTab === 'all') {
      return allMovePairs;
    }
    // 'played': only show moves up to currentMoveIndex
    if (currentMoveIndex < 0) return [];
    const pairs: MovePair[] = [];
    for (let i = 0; i <= currentMoveIndex; i += 2) {
      const moveNum = Math.floor(i / 2) + 1;
      const hasBlack = i + 1 <= currentMoveIndex;
      pairs.push({
        moveNumber: moveNum,
        whiteSan: samplePgnMoves[i],
        whiteIndex: i,
        blackSan: hasBlack ? samplePgnMoves[i + 1] : undefined,
        blackIndex: hasBlack ? i + 1 : undefined
      });
    }
    return pairs;
  });

  // Odds Graph Modal state and logic
  let showOddsModal = $state(false);
  let oddsModalTab = $state<'played' | 'all'>('played');
  let hoveredPointIndex = $state<number | null>(null);

  interface OddsDataPoint {
    plyIndex: number;
    moveNumber: number;
    color: 'White' | 'Black';
    san: string;
    yourOdds: number;
    theirOdds: number;
    timeRemaining: string;
    x: number;
    y: number;
  }

  const oddsGraphPoints = $derived.by(() => {
    const isPlayedOnly = oddsModalTab === 'played';
    const maxIndex = isPlayedOnly ? Math.max(0, currentMoveIndex) : evaluationOdds.length - 1;
    const count = maxIndex + 1;

    const svgWidth = 520;
    const svgHeight = 220;
    const padLeft = 45;
    const padRight = 25;
    const padTop = 25;
    const padBottom = 35;
    const plotW = svgWidth - padLeft - padRight;
    const plotH = svgHeight - padTop - padBottom;

    const points: OddsDataPoint[] = [];

    for (let i = 0; i < count; i++) {
      const val = evaluationOdds[i] ?? 50;
      const x = count > 1 ? padLeft + (i / (count - 1)) * plotW : padLeft + plotW / 2;
      const y = padTop + plotH - (val / 100) * plotH;
      const moveNum = Math.floor(i / 2) + 1;
      const isWhite = i % 2 === 0;
      const timeSec = isWhite
        ? Math.max(35, 600 - Math.floor((i + 2) / 2) * 14)
        : Math.max(18, 600 - Math.floor((i + 1) / 2) * 16);

      points.push({
        plyIndex: i,
        moveNumber: moveNum,
        color: isWhite ? 'White' : 'Black',
        san: samplePgnMoves[i] || '',
        yourOdds: val,
        theirOdds: 100 - val,
        timeRemaining: formatTime(timeSec),
        x,
        y
      });
    }

    return points;
  });

  const oddsSvgPath = $derived.by(() => {
    if (oddsGraphPoints.length === 0) return '';
    return oddsGraphPoints.reduce((acc, pt, i) => {
      return i === 0 ? `M ${pt.x} ${pt.y}` : `${acc} L ${pt.x} ${pt.y}`;
    }, '');
  });

  const oddsAreaPath = $derived.by(() => {
    if (oddsGraphPoints.length === 0) return '';
    const first = oddsGraphPoints[0];
    const last = oddsGraphPoints[oddsGraphPoints.length - 1];
    const bottomY = 220 - 35;
    return `${oddsSvgPath} L ${last.x} ${bottomY} L ${first.x} ${bottomY} Z`;
  });

  const activeInspectPoint = $derived.by(() => {
    if (hoveredPointIndex !== null && oddsGraphPoints[hoveredPointIndex]) {
      return oddsGraphPoints[hoveredPointIndex];
    }
    if (currentMoveIndex >= 0 && oddsGraphPoints[currentMoveIndex]) {
      return oddsGraphPoints[currentMoveIndex];
    }
    return oddsGraphPoints[0] || null;
  });

  onDestroy(() => {
    stopAutoPlay();
  });
</script>

<div class="analysis_page_container">
  <!-- Main Analysis Workspace -->
  <main class="analysis_workspace {viewMode === 'focused' ? 'focused_workspace' : ''}">
    <!-- Left Column: Interactive Chessboard -->
    <section class="board_section">
      <Chessboard fen={currentFen} onmove={handleMove} {viewMode} />
    </section>

    <!-- Right Column: Interactive Widgets -->
    <section class="widgets_section">
      {#if viewMode === 'expanded'}
        <!-- Replay button at top right of the section, aligned inline with rank 8 of the board -->
        <div class="widgets_header">
          <button
            class="mode_toggle_pill {gameCommentary.isPivotal ? 'pivotal_highlight' : ''}"
            onclick={() => (viewMode = 'focused')}
            title={gameCommentary.isPivotal ? `Pivotal Moment: ${gameCommentary.pivotalLabel || 'Critical move'}! Click to view in Replay mode` : 'Switch to Replay mode'}
            aria-label={gameCommentary.isPivotal ? `Pivotal Moment: ${gameCommentary.pivotalLabel || 'Critical move'}! Click to view in Replay mode` : 'Switch to Replay mode'}
          >
            {#if gameCommentary.isPivotal}
              <span class="pivotal_pulse_ring" aria-hidden="true"></span>
            {/if}
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
              <polyline points="15 3 21 3 21 9"></polyline>
              <polyline points="9 21 3 21 3 15"></polyline>
              <line x1="21" y1="3" x2="14" y2="10"></line>
              <line x1="3" y1="21" x2="10" y2="14"></line>
            </svg>
            <span>Replay</span>
            {#if gameCommentary.isPivotal}
              <span class="pivotal_badge_indicator">
                ⚡ {gameCommentary.pivotalLabel || 'Pivotal'}
              </span>
            {/if}
          </button>
        </div>

        <!-- EXPANDED ANALYSIS VIEW (expanded_analysis_page.png) -->
        <div class="expanded_grid">
          <!-- Row 1: Controls & Clock -->
          <div class="widget_box controls_widget_box">
            <h3 class="widget_heading">Controls</h3>

            {#if controlsMode === 'buttons'}
              <div class="controls_card">
                <button class="control_circle_btn" onclick={stepBackward} aria-label="Previous move" title="Previous move">
                  <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                    <polygon points="11 19 2 12 11 5 11 19"></polygon>
                    <polygon points="22 19 13 12 22 5 22 19"></polygon>
                  </svg>
                </button>

                <button class="control_circle_btn main_play_btn" onclick={toggleAutoPlay} aria-label={isPlaying ? 'Pause' : 'Play'} title={isPlaying ? 'Pause' : 'Play'}>
                  {#if isPlaying}
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                      <rect x="6" y="4" width="4" height="16"></rect>
                      <rect x="14" y="4" width="4" height="16"></rect>
                    </svg>
                  {:else}
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                      <polygon points="6 4 20 12 6 20 6 4"></polygon>
                    </svg>
                  {/if}
                </button>

                <button class="control_circle_btn" onclick={stepForward} aria-label="Next move" title="Next move">
                  <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                    <polygon points="13 19 22 12 13 5 13 19"></polygon>
                    <polygon points="2 19 11 12 2 5 2 19"></polygon>
                  </svg>
                </button>

                <!-- Switch button on the player -->
                <button
                  type="button"
                  class="control_mode_icon_btn"
                  onclick={toggleControlsMode}
                  aria-label="Switch to scrubber slider"
                  title="Switch to scrubber slider"
                >
                  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round">
                    <line x1="3" y1="8" x2="21" y2="8"></line>
                    <line x1="3" y1="16" x2="21" y2="16"></line>
                    <circle cx="8" cy="8" r="2.5" fill="currentColor"></circle>
                    <circle cx="16" cy="16" r="2.5" fill="currentColor"></circle>
                  </svg>
                </button>
              </div>
            {:else}
              <div class="controls_card scrubber_card">
                <!-- Switch back button on the player -->
                <button
                  type="button"
                  class="control_mode_icon_btn active_mode"
                  onclick={toggleControlsMode}
                  aria-label="Switch to playback buttons"
                  title="Switch to playback buttons"
                >
                  <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor">
                    <polygon points="6 4 18 12 6 20 6 4"></polygon>
                  </svg>
                </button>

                <div class="scrubber_body">
                  <div class="scrubber_labels_row">
                    <span class="scrubber_move_text">
                      {#if currentMoveIndex < 0}
                        Start
                      {:else}
                        <strong class="move_num_badge">{Math.floor(currentMoveIndex / 2) + 1}{currentMoveIndex % 2 === 0 ? '.' : '...'}</strong>
                        <span class="move_san_badge">{samplePgnMoves[currentMoveIndex]}</span>
                      {/if}
                    </span>
                    <span class="scrubber_progress_text">
                      {currentMoveIndex + 1} / {samplePgnMoves.length}
                    </span>
                  </div>

                  <div class="slider_wrapper">
                    <input
                      type="range"
                      min="-1"
                      max={samplePgnMoves.length - 1}
                      value={currentMoveIndex}
                      oninput={handleScrubberInput}
                      class="game_scrubber_range"
                      aria-label="Scrub through game moves"
                    />
                  </div>
                </div>
              </div>
            {/if}
          </div>

          <div class="widget_box clock_widget_box">
            <h3 class="widget_heading">Clock</h3>
            <div class="split_capsule clock_capsule">
              <div class="capsule_half black_half">
                <span class="clock_digits">{formatTime(youTime)}</span>
              </div>
              <div class="capsule_half gray_half">
                <span class="clock_digits">{formatTime(themTime)}</span>
              </div>
            </div>
          </div>

          <!-- Row 2: Odds & Moves -->
          <div class="widget_box odds_widget_box">
            <div class="widget_heading_row">
              <h3 class="widget_heading">Odds</h3>
              <button
                class="view_moves_btn"
                onclick={() => (showOddsModal = true)}
                title="View win odds progression graph"
                aria-label="Open odds graph modal"
              >
                <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
                </svg>
                <span>View Graph</span>
              </button>
            </div>
            <div
              class="split_capsule odds_capsule interactive_moves_card"
              onclick={() => (showOddsModal = true)}
              onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && (showOddsModal = true)}
              tabindex="0"
              role="button"
              title="Click to view odds progression graph"
              aria-label="Open odds progression graph modal"
            >
              <div class="capsule_half black_half">
                <span class="odds_percent">{yourOdds}%</span>
                <span class="odds_label">Your Odds</span>
              </div>
              <div class="capsule_half gray_half">
                <span class="odds_percent">{theirOdds}%</span>
                <span class="odds_label">Their Odds</span>
              </div>
            </div>
          </div>

          <div class="widget_box moves_widget_box">
            <div class="widget_heading_row">
              <h3 class="widget_heading">Moves</h3>
              <button
                class="view_moves_btn"
                onclick={() => (showMovesModal = true)}
                title="View full move list"
                aria-label="Open moves history modal"
              >
                <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
                  <line x1="8" y1="6" x2="21" y2="6"></line>
                  <line x1="8" y1="12" x2="21" y2="12"></line>
                  <line x1="8" y1="18" x2="21" y2="18"></line>
                  <line x1="3" y1="6" x2="3.01" y2="6"></line>
                  <line x1="3" y1="12" x2="3.01" y2="12"></line>
                  <line x1="3" y1="18" x2="3.01" y2="18"></line>
                </svg>
                <span>View Moves</span>
              </button>
            </div>
            <div
              class="moves_display_card interactive_moves_card"
              onclick={() => (showMovesModal = true)}
              onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && (showMovesModal = true)}
              tabindex="0"
              role="button"
              title="Click to view move history"
              aria-label="Open move history modal"
            >
              <div class="moves_column">
                <span class="moves_label">You</span>
                <span class="move_pill white_pill">
                  {activeWhiteMove}
                </span>
              </div>
              <div class="moves_divider"></div>
              <div class="moves_column">
                <span class="moves_label">Them</span>
                <span class="move_pill black_pill">
                  {activeBlackMove}
                </span>
              </div>
            </div>
          </div>

          <!-- Row 3: Live Commentary Text Box -->
          <div class="widget_box full_width_widget commentary_widget_box">
            <h3 class="widget_heading">Commentary</h3>
            <div class="commentary_card {gameCommentary.isPivotal ? 'pivotal_moment_card' : ''}">
              <div class="commentary_header">
                <div class="commentary_badge_group">
                  <span class="commentary_phase_badge">{gameCommentary.phase}</span>
                  {#if currentMoveIndex >= 0}
                    <span class="commentary_move_badge">
                      Move {Math.floor(currentMoveIndex / 2) + 1}{currentMoveIndex % 2 === 0 ? '.' : '...'} {samplePgnMoves[currentMoveIndex]}
                    </span>
                  {/if}
                  {#if gameCommentary.isPivotal}
                    <span class="commentary_pivotal_badge">
                      ⚡ Pivotal Moment
                    </span>
                  {/if}
                </div>
                <div class="commentary_live_indicator">
                  {#if wasPausedForPivotal}
                    <span class="pivotal_paused_badge">
                      <span class="paused_dot"></span>
                      Auto-Paused
                    </span>
                  {:else}
                    <span class="commentary_pulse_dot"></span>
                    <span>Live Analysis</span>
                  {/if}
                </div>
              </div>

              <h4 class="commentary_headline">{gameCommentary.headline}</h4>
              <p class="commentary_text">{gameCommentary.text}</p>
            </div>
          </div>
        </div>

      {:else}
        <!-- FOCUSED ANALYSIS VIEW (focused_analysis_page.png) -->
        <div class="focused_container">
          <div class="player_info_card top_player">
            <h2 class="player_display_name">{currentGame.opponent}</h2>
            <div class="player_stats_row">
              <span class="stat_badge">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="#38a169">
                  <path d="M12 2a3.5 3.5 0 0 0-3.5 3.5c0 1.25.66 2.34 1.63 2.94C8.75 9.28 8 10.74 8 12.5c0 .35.03.69.09 1.02C7.3 13.9 6.78 14.61 6.78 15.45c0 1.13.92 2.05 2.05 2.05h6.34c1.13 0 2.05-.92 2.05-2.05 0-.84-.52-1.55-1.31-1.93.06-.33.09-.67.09-1.02 0-1.76-.75-3.22-2.13-4.06.97-.6 1.63-1.69 1.63-2.94A3.5 3.5 0 0 0 12 2zm-5 18a1 1 0 0 0-1 1v1h12v-1a1 1 0 0 0-1-1H7z"/>
                </svg>
                1600
              </span>
              <span class="stat_badge">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="9"/>
                  <polyline points="12 6 12 12 16 14"/>
                </svg>
                1600
              </span>
            </div>
          </div>

          <!-- Middle Clock Widget (split capsule matching the concept mockup) -->
          <div class="focused_clock_section">
            <div class="split_capsule clock_capsule focused_clock_capsule">
              <div class="capsule_half black_half">
                <span class="clock_digits">{formatTime(youTime)}</span>
              </div>
              <div class="capsule_half gray_half">
                <span class="clock_digits">{formatTime(themTime)}</span>
              </div>
            </div>
          </div>

          <div class="player_info_card bottom_player">
            <h2 class="player_display_name">Saaketh Kesireddy</h2>
            <div class="player_stats_row">
              <span class="stat_badge">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="#38a169">
                  <path d="M12 2a3.5 3.5 0 0 0-3.5 3.5c0 1.25.66 2.34 1.63 2.94C8.75 9.28 8 10.74 8 12.5c0 .35.03.69.09 1.02C7.3 13.9 6.78 14.61 6.78 15.45c0 1.13.92 2.05 2.05 2.05h6.34c1.13 0 2.05-.92 2.05-2.05 0-.84-.52-1.55-1.31-1.93.06-.33.09-.67.09-1.02 0-1.76-.75-3.22-2.13-4.06.97-.6 1.63-1.69 1.63-2.94A3.5 3.5 0 0 0 12 2zm-5 18a1 1 0 0 0-1 1v1h12v-1a1 1 0 0 0-1-1H7z"/>
                </svg>
                1600
              </span>
              <span class="stat_badge">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="9"/>
                  <polyline points="12 6 12 12 16 14"/>
                </svg>
                1600
              </span>
            </div>
          </div>
        </div>
      {/if}
    </section>
  </main>

  {#if viewMode === 'focused'}
    <!-- Restart button in bottom right corner (matching focused_analysis_page.png) -->
    <div class="focused_bottom_bar">
      <button class="restart_pill_btn" onclick={() => { restartGame(); viewMode = 'expanded'; }}>
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
          <polyline points="1 4 1 10 7 10"></polyline>
          <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path>
        </svg>
        <span>Restart</span>
      </button>
    </div>
  {/if}

  {#if showMovesModal}
    <!-- Moves History Modal -->
    <div
      class="modal_backdrop"
      onclick={() => (showMovesModal = false)}
      onkeydown={(e) => e.key === 'Escape' && (showMovesModal = false)}
      tabindex="-1"
      role="presentation"
    >
      <div
        class="moves_modal_card"
        onclick={(e) => e.stopPropagation()}
        onkeydown={(e) => e.stopPropagation()}
        role="dialog"
        tabindex="-1"
        aria-modal="true"
        aria-labelledby="moves-modal-title"
      >
        <!-- Modal Header -->
        <div class="modal_header">
          <div>
            <h2 id="moves-modal-title" class="modal_title">Game Moves</h2>
            <p class="modal_subtitle">
              {#if currentMoveIndex < 0}
                Starting position • 0 of {samplePgnMoves.length} moves played
              {:else}
                Move {Math.floor(currentMoveIndex / 2) + 1} • {currentMoveIndex + 1} of {samplePgnMoves.length} plies played
              {/if}
            </p>
          </div>
          <button
            class="modal_close_btn"
            onclick={() => (showMovesModal = false)}
            aria-label="Close moves modal"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <!-- Mode Selector Tabs -->
        <div class="modal_tabs">
          <button
            class="tab_btn {movesModalTab === 'played' ? 'active_tab' : ''}"
            onclick={() => (movesModalTab = 'played')}
          >
            Up to Current Point ({Math.max(0, currentMoveIndex + 1)})
          </button>
          <button
            class="tab_btn {movesModalTab === 'all' ? 'active_tab' : ''}"
            onclick={() => (movesModalTab = 'all')}
          >
            All Moves ({samplePgnMoves.length})
          </button>
        </div>

        <!-- Moves List / Table -->
        <div class="moves_list_container">
          {#if movesModalTab === 'played' && currentMoveIndex < 0}
            <div class="empty_moves_notice">
              <p>No moves have been played yet.</p>
              <button class="step_forward_btn" onclick={() => { stepForward(); }}>
                Play First Move (1. {samplePgnMoves[0]})
              </button>
            </div>
          {:else}
            <div class="moves_table">
              <div class="moves_table_header">
                <span class="col_num">#</span>
                <span class="col_move">White (You)</span>
                <span class="col_move">Black (Them)</span>
              </div>
              
              <div class="moves_table_body">
                {#each displayedMovePairs as pair}
                  <div class="move_table_row">
                    <span class="col_num move_number">{pair.moveNumber}.</span>
                    
                    <!-- White Move -->
                    <button
                      class="move_item_btn {currentMoveIndex === pair.whiteIndex ? 'current_ply' : ''} {pair.whiteIndex > currentMoveIndex ? 'future_ply' : 'played_ply'}"
                      onclick={() => jumpToMove(pair.whiteIndex)}
                      title="Jump to move {pair.moveNumber} White ({pair.whiteSan})"
                    >
                      <span class="color_dot white_dot"></span>
                      <span class="san_text">{pair.whiteSan}</span>
                    </button>

                    <!-- Black Move -->
                    {#if pair.blackSan && pair.blackIndex !== undefined}
                      <button
                        class="move_item_btn {currentMoveIndex === pair.blackIndex ? 'current_ply' : ''} {pair.blackIndex > currentMoveIndex ? 'future_ply' : 'played_ply'}"
                        onclick={() => { if (pair.blackIndex !== undefined) jumpToMove(pair.blackIndex); }}
                        title="Jump to move {pair.moveNumber} Black ({pair.blackSan})"
                      >
                        <span class="color_dot black_dot"></span>
                        <span class="san_text">{pair.blackSan}</span>
                      </button>
                    {:else}
                      <span class="empty_move_placeholder">—</span>
                    {/if}
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        </div>

        <!-- Modal Footer -->
        <div class="modal_footer">
          <div class="footer_actions">
            <button class="footer_btn" onclick={() => jumpToMove(-1)}>
              Start
            </button>
            <button class="footer_btn" onclick={() => jumpToMove(samplePgnMoves.length - 1)}>
              End of Game
            </button>
          </div>
          <button class="done_btn" onclick={() => (showMovesModal = false)}>
            Done
          </button>
        </div>
      </div>
    </div>
  {/if}

  {#if showOddsModal}
    <!-- Odds Graph Modal -->
    <div
      class="modal_backdrop"
      onclick={() => (showOddsModal = false)}
      onkeydown={(e) => e.key === 'Escape' && (showOddsModal = false)}
      tabindex="-1"
      role="presentation"
    >
      <div
        class="moves_modal_card odds_modal_card"
        onclick={(e) => e.stopPropagation()}
        onkeydown={(e) => e.stopPropagation()}
        role="dialog"
        tabindex="-1"
        aria-modal="true"
        aria-labelledby="odds-modal-title"
      >
        <!-- Modal Header -->
        <div class="modal_header">
          <div>
            <h2 id="odds-modal-title" class="modal_title">Odds Over Time</h2>
            <p class="modal_subtitle">
              Win probability progression as a function of moves and clock time
            </p>
          </div>
          <button
            class="modal_close_btn"
            onclick={() => (showOddsModal = false)}
            aria-label="Close odds modal"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <!-- Mode Selector Tabs -->
        <div class="modal_tabs">
          <button
            class="tab_btn {oddsModalTab === 'played' ? 'active_tab' : ''}"
            onclick={() => (oddsModalTab = 'played')}
          >
            Up to Current Point ({Math.max(0, currentMoveIndex + 1)} moves)
          </button>
          <button
            class="tab_btn {oddsModalTab === 'all' ? 'active_tab' : ''}"
            onclick={() => (oddsModalTab = 'all')}
          >
            Full Game Timeline ({evaluationOdds.length} moves)
          </button>
        </div>

        <!-- Graph Container -->
        <div class="graph_container">
          <!-- Active Inspector HUD -->
          {#if activeInspectPoint}
            <div class="inspector_hud">
              <div class="hud_item">
                <span class="hud_label">Move</span>
                <span class="hud_value">
                  {activeInspectPoint.moveNumber}. {activeInspectPoint.san} ({activeInspectPoint.color})
                </span>
              </div>
              <div class="hud_divider"></div>
              <div class="hud_item">
                <span class="hud_label">Your Odds</span>
                <span class="hud_value your_val">{activeInspectPoint.yourOdds}%</span>
              </div>
              <div class="hud_divider"></div>
              <div class="hud_item">
                <span class="hud_label">Their Odds</span>
                <span class="hud_value their_val">{activeInspectPoint.theirOdds}%</span>
              </div>
              <div class="hud_divider"></div>
              <div class="hud_item">
                <span class="hud_label">Clock</span>
                <span class="hud_value">{activeInspectPoint.timeRemaining}</span>
              </div>
            </div>
          {/if}

          <!-- SVG Chart -->
          <div class="svg_wrapper">
            <svg viewBox="0 0 520 220" class="odds_chart_svg">
              <defs>
                <linearGradient id="oddsGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="#e8590c" stop-opacity="0.45" />
                  <stop offset="100%" stop-color="#e8590c" stop-opacity="0.02" />
                </linearGradient>
              </defs>

              <!-- Horizontal Grid Lines and Y-Axis Labels -->
              <!-- 100% -->
              <line x1="45" y1="25" x2="495" y2="25" stroke="#e0e0e0" stroke-width="1" />
              <text x="38" y="29" text-anchor="end" font-size="10" fill="#888">100%</text>

              <!-- 75% -->
              <line x1="45" y1="65" x2="495" y2="65" stroke="#efefef" stroke-width="1" />
              <text x="38" y="69" text-anchor="end" font-size="10" fill="#888">75%</text>

              <!-- 50% Baseline (Even Odds) -->
              <line x1="45" y1="105" x2="495" y2="105" stroke="#999999" stroke-width="1.2" stroke-dasharray="4 3" />
              <text x="38" y="109" text-anchor="end" font-size="10" fill="#555" font-weight="bold">50%</text>

              <!-- 25% -->
              <line x1="45" y1="145" x2="495" y2="145" stroke="#efefef" stroke-width="1" />
              <text x="38" y="149" text-anchor="end" font-size="10" fill="#888">25%</text>

              <!-- 0% -->
              <line x1="45" y1="185" x2="495" y2="185" stroke="#e0e0e0" stroke-width="1" />
              <text x="38" y="189" text-anchor="end" font-size="10" fill="#888">0%</text>

              <!-- X-Axis Labels -->
              <text x="45" y="206" text-anchor="start" font-size="10" fill="#888">Move 1 (Start)</text>
              <text x="495" y="206" text-anchor="end" font-size="10" fill="#888">
                Move {Math.floor((oddsGraphPoints.length - 1) / 2) + 1} ({oddsGraphPoints.length} plies)
              </text>

              <!-- Area under curve -->
              {#if oddsAreaPath}
                <path d={oddsAreaPath} fill="url(#oddsGrad)" />
              {/if}

              <!-- The Odds Curve -->
              {#if oddsSvgPath}
                <path
                  d={oddsSvgPath}
                  fill="none"
                  stroke="#e8590c"
                  stroke-width="3"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              {/if}

              <!-- Data Point Markers -->
              {#each oddsGraphPoints as pt, idx}
                <g
                  class="point_interactive_group"
                  role="button"
                  tabindex="0"
                  aria-label="Move {pt.moveNumber} {pt.color}: {pt.yourOdds}% win odds"
                  onmouseenter={() => (hoveredPointIndex = idx)}
                  onmouseleave={() => (hoveredPointIndex = null)}
                  onfocus={() => (hoveredPointIndex = idx)}
                  onblur={() => (hoveredPointIndex = null)}
                  onclick={() => jumpToMove(pt.plyIndex)}
                  onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && jumpToMove(pt.plyIndex)}
                >
                  <!-- Hit target circle for easy hovering & clicking -->
                  <circle
                    cx={pt.x}
                    cy={pt.y}
                    r="8"
                    fill="transparent"
                    class="point_target"
                  />

                  <!-- Visible point circle -->
                  <circle
                    cx={pt.x}
                    cy={pt.y}
                    r={currentMoveIndex === pt.plyIndex || hoveredPointIndex === idx ? 5 : 2.5}
                    fill={currentMoveIndex === pt.plyIndex ? '#e8590c' : '#ffffff'}
                    stroke={currentMoveIndex === pt.plyIndex ? '#000000' : '#e8590c'}
                    stroke-width={currentMoveIndex === pt.plyIndex ? 2.5 : 1.5}
                    class="visible_point {currentMoveIndex === pt.plyIndex ? 'current_point' : ''}"
                  />
                </g>
              {/each}
            </svg>
          </div>

          <div class="graph_hint">
            <span>Tip: Hover or tap any point along the curve to inspect odds and jump directly to that move!</span>
          </div>
        </div>

        <!-- Modal Footer -->
        <div class="modal_footer">
          <div class="footer_actions">
            <button class="footer_btn" onclick={() => jumpToMove(-1)}>
              Start (50%)
            </button>
            <button class="footer_btn" onclick={() => jumpToMove(evaluationOdds.length - 1)}>
              End (100%)
            </button>
          </div>
          <button class="done_btn" onclick={() => (showOddsModal = false)}>
            Done
          </button>
        </div>
      </div>
    </div>
  {/if}
</div>

<style>
  .analysis_page_container {
    max-width: 1400px;
    margin: 0 auto;
    padding: max(1.5rem, calc(50vh - 400px)) 2rem 2.5rem 2rem;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  /* Widgets Header (Replay button) */
  .widgets_header {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    margin-bottom: 1.25rem;
    width: 100%;
  }

  .mode_toggle_pill {
    background: var(--accent-1, #e8590c);
    color: #000000;
    border: none;
    border-radius: 40px;
    padding: 0.55rem 1.4rem;
    font-size: 15px;
    font-weight: 700;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    cursor: pointer;
    transition: transform 0.15s ease, opacity 0.15s ease;
  }

  .mode_toggle_pill:hover {
    transform: translateY(-2px);
    opacity: 0.92;
  }

  /* Pivotal Moment Highlight Ring on Replay Button */
  .mode_toggle_pill.pivotal_highlight {
    position: relative;
    box-shadow: 0 0 0 0 rgba(232, 89, 12, 0.7);
    animation: pivotalButtonPulse 2.2s infinite cubic-bezier(0.66, 0, 0, 1);
  }

  @keyframes pivotalButtonPulse {
    0% {
      box-shadow: 0 0 0 0 rgba(232, 89, 12, 0.8), 0 0 14px rgba(232, 89, 12, 0.45);
    }
    70% {
      box-shadow: 0 0 0 10px rgba(232, 89, 12, 0), 0 0 24px rgba(232, 89, 12, 0);
    }
    100% {
      box-shadow: 0 0 0 0 rgba(232, 89, 12, 0), 0 0 0 rgba(232, 89, 12, 0);
    }
  }

  .pivotal_pulse_ring {
    position: absolute;
    inset: -6px;
    border-radius: 999px;
    border: 2px solid var(--accent-1, #e8590c);
    opacity: 0.85;
    pointer-events: none;
    animation: pivotalRingPulse 2.2s infinite ease-out;
  }

  @keyframes pivotalRingPulse {
    0% {
      transform: scale(0.97);
      opacity: 0.95;
      border-width: 2.5px;
    }
    50% {
      transform: scale(1.06);
      opacity: 0.55;
      border-width: 1.5px;
    }
    100% {
      transform: scale(1.14);
      opacity: 0;
      border-width: 1px;
    }
  }

  .pivotal_badge_indicator {
    font-size: 11px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    background: #000000;
    color: #ffffff;
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
    display: inline-flex;
    align-items: center;
    gap: 0.2rem;
    margin-left: 0.35rem;
    animation: pivotalBadgeGlow 1.6s infinite alternate ease-in-out;
  }

  @keyframes pivotalBadgeGlow {
    0% {
      transform: scale(0.98);
      box-shadow: 0 0 3px rgba(0, 0, 0, 0.4);
    }
    100% {
      transform: scale(1.04);
      box-shadow: 0 0 8px rgba(0, 0, 0, 0.7);
    }
  }

  /* Main Workspace */
  .analysis_workspace {
    display: flex;
    gap: 3.5rem;
    align-items: flex-start;
    justify-content: center;
    width: 100%;
    max-width: 1250px;
    margin: 0 auto;
  }

  .board_section {
    flex: 0 0 580px;
    max-width: 580px;
    width: 100%;
    display: flex;
    justify-content: center;
  }

  .widgets_section {
    flex: 0 0 580px;
    max-width: 580px;
    width: 100%;
    display: flex;
    flex-direction: column;
  }

  /* Expanded Grid */
  .expanded_grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5rem;
    width: 100%;
  }

  .widget_box {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .full_width_widget {
    grid-column: 1 / -1;
  }

  .widget_heading {
    font-size: 18px;
    font-weight: 700;
    color: #000000;
    margin: 0;
  }

  /* Controls Card */
  .controls_card {
    background: #d8d8d8;
    border-radius: 18px;
    height: 72px;
    display: flex;
    align-items: center;
    justify-content: space-evenly;
    padding: 0 0.85rem;
    box-sizing: border-box;
    transition: all 0.2s ease;
  }

  .control_circle_btn {
    width: 44px;
    height: 44px;
    border-radius: 50%;
    background: var(--accent-1, #e8590c);
    border: none;
    color: #ffffff;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: transform 0.15s ease, opacity 0.15s ease;
  }

  .control_circle_btn:hover {
    transform: scale(1.08);
  }

  .control_mode_icon_btn {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: #c2c2c2;
    border: none;
    color: #2b2b2b;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.18s ease;
    flex-shrink: 0;
  }

  .control_mode_icon_btn:hover {
    background: #000000;
    color: #ffffff;
    transform: scale(1.08);
  }

  .control_mode_icon_btn.active_mode {
    background: #000000;
    color: #ffffff;
  }

  /* Scrubber Mode */
  .scrubber_card {
    justify-content: flex-start;
    gap: 0.85rem;
    padding: 0.5rem 1rem;
  }

  .scrubber_body {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 0.4rem;
    min-width: 0;
  }

  .scrubber_labels_row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 12px;
    line-height: 1;
  }

  .scrubber_move_text {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    font-weight: 700;
    color: #111111;
  }

  .move_num_badge {
    color: #333333;
    font-weight: 800;
  }

  .move_san_badge {
    background: var(--accent-1, #e8590c);
    color: #ffffff;
    padding: 0.12rem 0.45rem;
    border-radius: 6px;
    font-size: 11.5px;
    font-weight: 700;
    letter-spacing: 0.02em;
  }

  .scrubber_progress_text {
    font-size: 11px;
    font-weight: 700;
    color: #555555;
    background: rgba(0, 0, 0, 0.07);
    padding: 0.15rem 0.45rem;
    border-radius: 6px;
  }

  .slider_wrapper {
    display: flex;
    align-items: center;
    width: 100%;
  }

  .game_scrubber_range {
    -webkit-appearance: none;
    appearance: none;
    width: 100%;
    height: 7px;
    border-radius: 999px;
    background: #b5b5b5;
    outline: none;
    cursor: pointer;
    margin: 0;
    transition: background 0.15s ease;
  }

  .game_scrubber_range::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 19px;
    height: 19px;
    border-radius: 50%;
    background: var(--accent-1, #e8590c);
    border: 2.5px solid #ffffff;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.28);
    cursor: pointer;
    transition: transform 0.15s ease;
  }

  .game_scrubber_range::-moz-range-thumb {
    width: 19px;
    height: 19px;
    border-radius: 50%;
    background: var(--accent-1, #e8590c);
    border: 2.5px solid #ffffff;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.28);
    cursor: pointer;
    transition: transform 0.15s ease;
  }

  .game_scrubber_range:hover::-webkit-slider-thumb {
    transform: scale(1.22);
  }

  .game_scrubber_range:hover::-moz-range-thumb {
    transform: scale(1.22);
  }

  /* Split Capsules (Odds & Clock) */
  .split_capsule {
    height: 72px;
    border-radius: 20px;
    display: flex;
    overflow: hidden;
    background: #d8d8d8;
  }

  .capsule_half {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }

  .black_half {
    background: #000000;
    color: #ffffff;
    border-radius: 20px 0 0 20px;
  }

  .gray_half {
    background: #d8d8d8;
    color: #000000;
  }

  .odds_percent {
    font-size: 20px;
    font-weight: 700;
    line-height: 1.1;
  }

  .odds_label {
    font-size: 11px;
    font-weight: 600;
    opacity: 0.85;
    margin-top: 2px;
  }

  /* Clock digits */
  .clock_digits {
    font-family: 'Times New Roman', Times, serif;
    font-size: 28px;
    font-weight: 400;
    letter-spacing: 1px;
  }

  /* Moves Card */
  .moves_display_card {
    background: #d8d8d8;
    border-radius: 20px;
    height: 72px;
    display: flex;
    align-items: center;
    padding: 0.5rem 1rem;
    box-sizing: border-box;
  }

  .moves_column {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }

  .moves_label {
    font-size: 13px;
    font-weight: 700;
    color: #000000;
  }

  .move_pill {
    padding: 0.2rem 1.1rem;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 700;
  }

  .white_pill {
    background: #ffffff;
    color: #000000;
  }

  .black_pill {
    background: #000000;
    color: #ffffff;
  }

  .moves_divider {
    width: 1px;
    height: 100%;
    background: #8e8e8e;
  }

  /* Commentary Section */
  .commentary_card {
    background: #d8d8d8;
    border-radius: 20px;
    padding: 1.15rem 1.4rem;
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
    box-sizing: border-box;
    transition: all 0.2s ease;
  }

  .commentary_card.pivotal_moment_card {
    border-left: 4px solid var(--accent-1, #e8590c);
    box-shadow: 0 2px 10px rgba(232, 89, 12, 0.15);
  }

  .commentary_pivotal_badge {
    font-size: 11px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    background: linear-gradient(135deg, #e8590c, #f76707);
    color: #ffffff;
    padding: 0.22rem 0.65rem;
    border-radius: 999px;
    box-shadow: 0 1px 4px rgba(232, 89, 12, 0.35);
    animation: pivotalBadgeGlow 1.6s infinite alternate ease-in-out;
  }

  .commentary_header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.25rem;
  }

  .commentary_badge_group {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .commentary_phase_badge {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    background: #000000;
    color: #ffffff;
    padding: 0.22rem 0.65rem;
    border-radius: 999px;
  }

  .commentary_move_badge {
    font-size: 11px;
    font-weight: 700;
    background: var(--accent-1, #e8590c);
    color: #ffffff;
    padding: 0.22rem 0.65rem;
    border-radius: 999px;
  }

  .commentary_live_indicator {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 11.5px;
    font-weight: 700;
    color: #4b5563;
  }

  .pivotal_paused_badge {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 10.5px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    background: #000000;
    color: #ffb703;
    padding: 0.18rem 0.55rem;
    border-radius: 999px;
    animation: pausePulse 1.8s infinite ease-in-out;
  }

  .paused_dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #ffb703;
    box-shadow: 0 0 5px rgba(255, 183, 3, 0.8);
  }

  @keyframes pausePulse {
    0%, 100% {
      opacity: 1;
      transform: scale(1);
    }
    50% {
      opacity: 0.85;
      transform: scale(1.03);
    }
  }

  .commentary_pulse_dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #10b981;
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
    animation: pulseDot 2s infinite;
  }

  @keyframes pulseDot {
    0% {
      transform: scale(0.95);
      box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
    }
    70% {
      transform: scale(1);
      box-shadow: 0 0 0 6px rgba(16, 185, 129, 0);
    }
    100% {
      transform: scale(0.95);
      box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
    }
  }

  .commentary_headline {
    font-size: 16px;
    font-weight: 800;
    color: #111111;
    margin: 0;
    line-height: 1.3;
  }

  .commentary_text {
    font-size: 14px;
    line-height: 1.55;
    color: #262626;
    margin: 0;
    font-weight: 500;
  }

  /* Focused View (focused_analysis_page.png) */
  .analysis_workspace.focused_workspace {
    justify-content: center;
    align-items: center;
    gap: 3.5rem;
    min-height: calc(85vh - 70px);
    width: 100%;
    margin: 0 auto;
  }

  .analysis_workspace.focused_workspace .board_section {
    flex: 0 0 580px;
    width: 580px;
    max-width: 580px;
    display: flex;
    justify-content: center;
  }

  .analysis_workspace.focused_workspace .widgets_section {
    flex: 0 0 auto;
    width: 270px;
    min-width: 270px;
  }

  .focused_container {
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    height: 580px;
    max-height: 580px;
    box-sizing: border-box;
  }

  .focused_clock_section {
    display: flex;
    justify-content: flex-start;
    width: 100%;
    margin: 1rem 0;
  }

  .focused_clock_capsule {
    width: 100%;
    height: 72px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  }

  .player_info_card {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }

  .focused_bottom_bar {
    position: fixed;
    bottom: 2.25rem;
    right: 2.5rem;
    z-index: 50;
  }

  .player_display_name {
    font-size: 22px;
    font-weight: 700;
    color: #000000;
    margin: 0;
  }

  .player_stats_row {
    display: flex;
    align-items: center;
    gap: 1rem;
  }

  .stat_badge {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 15px;
    font-weight: 700;
    color: #000000;
  }

  .restart_pill_btn {
    background: #d8d8d8;
    border: none;
    border-radius: 20px;
    padding: 0.5rem 1.25rem;
    font-size: 14px;
    font-weight: 700;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
    transition: background 0.15s ease, transform 0.15s ease;
  }

  .restart_pill_btn:hover {
    background: #c8c8c8;
    transform: translateY(-1px);
  }

  /* Moves Widget Heading & Card */
  .widget_heading_row {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .view_moves_btn {
    background: #e4e4e4;
    border: none;
    border-radius: 14px;
    padding: 0.22rem 0.65rem;
    font-size: 12px;
    font-weight: 700;
    color: #333333;
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .view_moves_btn:hover {
    background: #d4d4d4;
    color: #000000;
    transform: translateY(-1px);
  }

  .interactive_moves_card {
    cursor: pointer;
    border: none;
    width: 100%;
    text-align: left;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }

  .interactive_moves_card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.1);
  }

  /* Moves History Modal */
  .modal_backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(2px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    padding: 1rem;
    box-sizing: border-box;
  }

  .moves_modal_card {
    background: #ffffff;
    border-radius: 20px;
    box-shadow: 0 20px 45px rgba(0, 0, 0, 0.25);
    width: 100%;
    max-width: 480px;
    max-height: 85vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    animation: modalPop 0.18s ease-out;
  }

  @keyframes modalPop {
    from {
      opacity: 0;
      transform: scale(0.96) translateY(6px);
    }
    to {
      opacity: 1;
      transform: scale(1) translateY(0);
    }
  }

  .modal_header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    padding: 1.25rem 1.5rem 1rem 1.5rem;
    border-bottom: 1px solid #ebebeb;
  }

  .modal_title {
    font-size: 20px;
    font-weight: 800;
    color: #000000;
    margin: 0;
  }

  .modal_subtitle {
    font-size: 13px;
    color: #666666;
    margin: 0.25rem 0 0 0;
    font-weight: 500;
  }

  .modal_close_btn {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: #f0f0f0;
    border: none;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    color: #444444;
    transition: background 0.15s ease, color 0.15s ease;
    flex-shrink: 0;
  }

  .modal_close_btn:hover {
    background: #e2e2e2;
    color: #000000;
  }

  /* Modal Tabs */
  .modal_tabs {
    display: flex;
    background: #f2f2f2;
    padding: 0.3rem;
    margin: 1rem 1.5rem 0.5rem 1.5rem;
    border-radius: 12px;
    gap: 0.3rem;
  }

  .tab_btn {
    flex: 1;
    border: none;
    background: transparent;
    padding: 0.5rem 0.75rem;
    font-size: 13px;
    font-weight: 700;
    color: #666666;
    border-radius: 9px;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .tab_btn.active_tab {
    background: #ffffff;
    color: #000000;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
  }

  /* Moves List & Table */
  .moves_list_container {
    flex: 1;
    overflow-y: auto;
    padding: 0.75rem 1.5rem 1rem 1.5rem;
    max-height: 380px;
  }

  .empty_moves_notice {
    text-align: center;
    padding: 2.5rem 1rem;
    color: #777777;
    font-size: 14px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1rem;
  }

  .step_forward_btn {
    background: var(--accent-1, #e8590c);
    color: #000000;
    border: none;
    border-radius: 20px;
    padding: 0.55rem 1.25rem;
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
    transition: opacity 0.15s ease;
  }

  .step_forward_btn:hover {
    opacity: 0.9;
  }

  .moves_table {
    display: flex;
    flex-direction: column;
    width: 100%;
  }

  .moves_table_header {
    display: grid;
    grid-template-columns: 48px 1fr 1fr;
    padding: 0.45rem 0.5rem;
    font-size: 12px;
    font-weight: 700;
    color: #888888;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 1px solid #f0f0f0;
  }

  .moves_table_body {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    margin-top: 0.4rem;
  }

  .move_table_row {
    display: grid;
    grid-template-columns: 48px 1fr 1fr;
    align-items: center;
    padding: 0.25rem 0.2rem;
    border-radius: 10px;
    transition: background 0.12s ease;
  }

  .move_table_row:hover {
    background: #f8f8f8;
  }

  .move_number {
    font-size: 13px;
    font-weight: 700;
    color: #888888;
    padding-left: 0.35rem;
  }

  .move_item_btn {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    padding: 0.45rem 0.75rem;
    border: 1px solid transparent;
    background: #f2f2f2;
    border-radius: 8px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 700;
    color: #111111;
    margin-right: 0.4rem;
    transition: all 0.15s ease;
  }

  .move_item_btn:hover {
    background: #e5e5e5;
    transform: translateY(-1px);
  }

  .move_item_btn.current_ply {
    background: var(--accent-1, #e8590c);
    color: #000000;
    font-weight: 800;
    box-shadow: 0 2px 8px rgba(232, 89, 12, 0.3);
  }

  .move_item_btn.future_ply {
    opacity: 0.55;
    background: #fafafa;
  }

  .color_dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .white_dot {
    background: #ffffff;
    border: 1px solid #777777;
  }

  .black_dot {
    background: #000000;
  }

  .empty_move_placeholder {
    color: #bbb;
    padding-left: 1rem;
    font-size: 14px;
  }

  .modal_footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.85rem 1.5rem;
    border-top: 1px solid #ebebeb;
    background: #fafafa;
  }

  .footer_actions {
    display: flex;
    gap: 0.5rem;
  }

  .footer_btn {
    background: #e8e8e8;
    border: none;
    border-radius: 8px;
    padding: 0.4rem 0.75rem;
    font-size: 12px;
    font-weight: 700;
    color: #333333;
    cursor: pointer;
    transition: background 0.15s ease;
  }

  .footer_btn:hover {
    background: #dadada;
  }

  .done_btn {
    background: #000000;
    color: #ffffff;
    border: none;
    border-radius: 10px;
    padding: 0.5rem 1.25rem;
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
    transition: opacity 0.15s ease;
  }

  .done_btn:hover {
    opacity: 0.85;
  }

  /* Odds Graph Modal Specifics */
  .odds_modal_card {
    max-width: 560px;
  }

  .graph_container {
    padding: 0.75rem 1.5rem 1rem 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.85rem;
  }

  .inspector_hud {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #f7f7f7;
    border: 1px solid #e8e8e8;
    border-radius: 12px;
    padding: 0.6rem 1rem;
  }

  .hud_item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
  }

  .hud_label {
    font-size: 11px;
    font-weight: 600;
    color: #777777;
    text-transform: uppercase;
  }

  .hud_value {
    font-size: 13px;
    font-weight: 700;
    color: #111111;
  }

  .hud_value.your_val {
    color: #e8590c;
  }

  .hud_value.their_val {
    color: #333333;
  }

  .hud_divider {
    width: 1px;
    height: 24px;
    background: #e0e0e0;
  }

  .svg_wrapper {
    width: 100%;
    background: #fafafa;
    border-radius: 14px;
    border: 1px solid #ebebeb;
    padding: 0.5rem 0.25rem 0.25rem 0.25rem;
    box-sizing: border-box;
  }

  .odds_chart_svg {
    width: 100%;
    height: auto;
    display: block;
    user-select: none;
  }

  .point_target {
    cursor: pointer;
  }

  .visible_point {
    pointer-events: none;
    transition: r 0.15s ease, stroke-width 0.15s ease;
  }

  .current_point {
    filter: drop-shadow(0 2px 5px rgba(232, 89, 12, 0.45));
  }

  .graph_hint {
    font-size: 11px;
    color: #777777;
    text-align: center;
    line-height: 1.35;
    padding: 0 0.5rem;
  }

  /* Responsive Mobile Layout */
  @media screen and (max-width: 900px) {
    .analysis_page_container {
      padding: 1rem;
      min-height: auto;
    }

    .widgets_header {
      margin-bottom: 1.5rem;
      width: 100%;
    }

    .mode_toggle_pill {
      width: 100%;
      justify-content: center;
      padding: 0.9rem 1.5rem;
      font-size: 18px;
      gap: 0.65rem;
      border-radius: 50px;
      box-sizing: border-box;
    }

    .mode_toggle_pill svg {
      width: 22px;
      height: 22px;
    }

    .analysis_workspace {
      flex-direction: column;
      align-items: center;
    }

    /* Expanded Mode on Mobile:
       1. Commentary at the top
       2. Chessboard
       3. Controls (play / scrubber)
       4. Clock
       5. Moves
       6. Odds
       7. Replay Button
    */
    .analysis_workspace:not(.focused_workspace) {
      flex-direction: column;
      align-items: center;
      gap: 0.85rem;
    }

    .analysis_workspace:not(.focused_workspace) .widgets_section {
      display: contents;
    }

    .analysis_workspace:not(.focused_workspace) .expanded_grid {
      display: contents;
    }

    .analysis_workspace:not(.focused_workspace) .commentary_widget_box {
      order: 1;
      width: 100%;
      max-width: 580px;
      margin-bottom: 0.25rem;
    }

    .analysis_workspace:not(.focused_workspace) .commentary_widget_box .widget_heading {
      display: none;
    }

    .analysis_workspace:not(.focused_workspace) .board_section {
      order: 2;
      width: 100%;
      max-width: 580px;
      flex: 0 0 auto;
    }

    .analysis_workspace:not(.focused_workspace) .widgets_header {
      order: 3;
      width: 100%;
      max-width: 580px;
      margin-top: 0.5rem;
      margin-bottom: 0.25rem;
    }

    .analysis_workspace:not(.focused_workspace) .controls_widget_box {
      order: 4;
      width: 100%;
      max-width: 580px;
      margin-top: 0.25rem;
    }

    .analysis_workspace:not(.focused_workspace) .clock_widget_box {
      order: 5;
      width: 100%;
      max-width: 580px;
    }

    .analysis_workspace:not(.focused_workspace) .odds_widget_box {
      order: 6;
      width: 100%;
      max-width: 580px;
    }

    .analysis_workspace:not(.focused_workspace) .moves_widget_box {
      order: 7;
      width: 100%;
      max-width: 580px;
      margin-bottom: 1.5rem;
    }

    /* Focused Mode on Mobile:
       1. Opponent name on top
       2. Chessboard in middle
       3. Your name on bottom
       4. Clock below your name
       5. Restart button below clock
    */
    .analysis_workspace.focused_workspace {
      flex-direction: column;
      align-items: center;
      min-height: auto;
      gap: 0.75rem;
      width: 100%;
    }

    .analysis_workspace.focused_workspace .widgets_section {
      display: contents;
    }

    .analysis_workspace.focused_workspace .focused_container {
      display: contents;
    }

    .analysis_workspace.focused_workspace .top_player {
      order: 1;
      width: 100%;
      max-width: 580px;
      margin-bottom: 0.25rem;
    }

    .analysis_workspace.focused_workspace .board_section {
      order: 2;
      width: 100%;
      max-width: 580px;
      flex: 0 0 auto;
    }

    .analysis_workspace.focused_workspace .bottom_player {
      order: 3;
      width: 100%;
      max-width: 580px;
      margin-top: 0.5rem;
    }

    .analysis_workspace.focused_workspace .focused_clock_section {
      order: 4;
      width: 100%;
      max-width: 580px;
      display: flex;
      justify-content: center;
      margin: 0.75rem 0 0.25rem 0;
    }

    .analysis_workspace.focused_workspace .focused_clock_capsule {
      width: 100%;
      max-width: 320px;
    }

    .board_section,
    .widgets_section {
      width: 100%;
    }

    .expanded_grid {
      grid-template-columns: 1fr;
    }

    .focused_bottom_bar {
      position: static;
      display: flex;
      justify-content: flex-end;
      margin-top: 1.25rem;
      width: 100%;
      max-width: 580px;
      margin-left: auto;
      margin-right: auto;
    }
  }
</style>
