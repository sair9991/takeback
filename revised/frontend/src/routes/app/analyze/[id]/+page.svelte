<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { page } from '$app/state';
  import { Chess } from 'chess.js';
  import Chessboard from '../../../../lib/components/Chessboard.svelte';
  import { getGameAnalysis, fetchGameDetail, fetchGameMoves, type CommentaryMoment, type MoveRecord } from '../../../../lib/functions/gameAnalysis';
  import { requestCloneMove } from '../../../../lib/functions/clones';
  import type { Game } from '../../../../lib/types/game';

  const gameId = $derived(page.params.id);

  // Real game metadata, moves, and odds fetched from backend
  let activeGame = $state<Game | null>(null);
  let realMoves = $state<string[]>([]);
  let realRecords = $state<MoveRecord[]>([]);
  let realOdds = $state<number[]>([]);
  let realCommentary = $state<CommentaryMoment[]>([]);
  let realNarrative = $state<string>('');
  let backendError = $state<string | null>(null);
  let isLoadingGame = $state(true);
  let isCommentaryLoading = $state(false);
  let pollInterval: ReturnType<typeof setInterval> | null = null;

  onDestroy(() => {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
  });

  function startCommentaryPolling() {
    if (pollInterval) return;
    isCommentaryLoading = true;
    let attempts = 0;
    pollInterval = setInterval(async () => {
      attempts++;
      if (attempts > 35) {
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = null;
        isCommentaryLoading = false;
        return;
      }
      try {
        const update = await fetchGameDetail(gameId);
        if ((update.commentary && update.commentary.length > 0) || update.narrative) {
          if (update.commentary && update.commentary.length > 0) {
            realCommentary = update.commentary;
          }
          if (update.narrative) {
            realNarrative = update.narrative;
          }
          if (!update.is_generating) {
            isCommentaryLoading = false;
            if (pollInterval) clearInterval(pollInterval);
            pollInterval = null;
          }
        }
      } catch (e) {
        // continue polling until timeout
      }
    }, 2000);
  }

  const currentGame = $derived(
    activeGame || {
      id: gameId,
      opponent: 'Opponent',
      date: '',
      platform: 'Chess.com'
    }
  );

  onMount(async () => {
    if (gameId) {
      isLoadingGame = true;
      try {
        const detail = await fetchGameDetail(gameId);
        if (detail.error) {
          backendError = detail.error;
        }
        if (detail.game) {
          activeGame = detail.game;
        } else {
          try {
            const { fetchUserGames } = await import('../../../../lib/functions/userGames');
            const allUserGames = await fetchUserGames();
            const matched = allUserGames.find((g) => g.id === gameId || String(g.id) === String(gameId));
            if (matched) activeGame = matched;
          } catch (e) {
            console.warn('Game lookup failed:', e);
          }
        }
        if (detail.moves && detail.moves.length > 0) {
          realMoves = detail.moves;
          realRecords = detail.records;
          restartGame();
        }
        if (detail.odds && detail.odds.length > 0) {
          realOdds = detail.odds;
        }
        if (detail.commentary && detail.commentary.length > 0) {
          realCommentary = detail.commentary;
        }
        if (detail.narrative) {
          realNarrative = detail.narrative;
        }
        if (detail.is_generating || (realCommentary.length === 0 && !realNarrative)) {
          startCommentaryPolling();
        }
      } finally {
        isLoadingGame = false;
      }
    }
  });

  const samplePgnMoves = $derived(realMoves);
  const evaluationOdds = $derived.by(() => {
    if (realOdds.length > 0) {
      return realOdds;
    }
    return samplePgnMoves.map(() => 50);
  });

  // Chess game logic using chess.js
  let chess = new Chess();
  let currentFen = $state(chess.fen());
  let moveHistory = $state<string[]>([]);

  // View mode: 'expanded' (controls, odds, clock, chat) vs 'focused' (players, ratings)
  let viewMode = $state<'expanded' | 'focused'>('expanded');

  let currentMoveIndex = $state(-1);
  let isPlaying = $state(false);
  let playInterval: ReturnType<typeof setInterval> | null = null;

  // Active odds
  let yourOdds = $derived(
    currentMoveIndex >= 0 && currentMoveIndex < evaluationOdds.length
      ? Math.round(evaluationOdds[currentMoveIndex] * 10) / 10
      : 50
  );
  let theirOdds = $derived(Math.round((100 - yourOdds) * 10) / 10);

  function formatOdds(val: number): string {
    return (Math.round(val * 10) / 10).toString();
  }

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

  // Clocks calculated from moves made (uses real database time_remaining if available)
  let youTime = $derived.by(() => {
    if (currentMoveIndex < 0) return 600;
    if (realRecords.length > 0) {
      for (let i = currentMoveIndex; i >= 0; i--) {
        if (realRecords[i]?.side === 'white' && realRecords[i]?.time_remaining != null) {
          return Math.round(realRecords[i].time_remaining);
        }
      }
    }
    const whiteMovesCount = Math.floor((currentMoveIndex + 2) / 2);
    return Math.max(35, 600 - whiteMovesCount * 14);
  });

  let themTime = $derived.by(() => {
    if (currentMoveIndex < 1) return 600;
    if (realRecords.length > 0) {
      for (let i = currentMoveIndex; i >= 0; i--) {
        if (realRecords[i]?.side === 'black' && realRecords[i]?.time_remaining != null) {
          return Math.round(realRecords[i].time_remaining);
        }
      }
    }
    const blackMovesCount = Math.floor((currentMoveIndex + 1) / 2);
    return Math.max(18, 600 - blackMovesCount * 16);
  });

  function formatTime(seconds: number): string {
    const totalSecs = Math.max(0, Math.round(seconds));
    const mins = Math.floor(totalSecs / 60);
    const secs = totalSecs % 60;
    return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
  }

  // Interactive Replay against Clone state
  let replayYouTime = $state<number | null>(null);
  let replayThemTime = $state<number | null>(null);
  let isCloneThinking = $state(false);
  let replayTimerInterval: ReturnType<typeof setInterval> | null = null;

  function startReplayClock() {
    stopReplayClock();
    replayTimerInterval = setInterval(() => {
      if (viewMode !== 'focused' || chess.isGameOver()) {
        stopReplayClock();
        return;
      }

      if (isOpponentTurn || isCloneThinking) {
        // Opponent's turn: tick opponent's clock down
        if (replayThemTime != null && replayThemTime > 0) {
          replayThemTime = Math.max(0, replayThemTime - 1);
        }
      } else {
        // Player's turn: tick player's clock down second by second
        if (replayYouTime != null && replayYouTime > 0) {
          replayYouTime = Math.max(0, replayYouTime - 1);
        }
      }
    }, 1000);
  }

  function stopReplayClock() {
    if (replayTimerInterval) {
      clearInterval(replayTimerInterval);
      replayTimerInterval = null;
    }
  }

  const playerColor = $derived.by<'white' | 'black'>(() => {
    const raw = (currentGame.player_color || 'white').toLowerCase().trim();
    return raw === 'black' ? 'black' : 'white';
  });
  const opponentColor = $derived<'white' | 'black'>(playerColor === 'white' ? 'black' : 'white');

  // Reactive check using currentFen ($state) to ensure Svelte 5 triggers on every move
  const isOpponentTurn = $derived.by(() => {
    const turn = currentFen.split(' ')[1] || 'w';
    return (turn === 'w' && playerColor === 'black') ||
           (turn === 'b' && playerColor === 'white');
  });

  const currentYouTime = $derived(replayYouTime ?? youTime);
  const currentThemTime = $derived(replayThemTime ?? themTime);

  async function triggerCloneMove() {
    if (isCloneThinking || chess.isGameOver()) return;
    const turn = currentFen.split(' ')[1] || 'w';
    const isTheirTurn = (turn === 'w' && playerColor === 'black') || (turn === 'b' && playerColor === 'white');
    if (!isTheirTurn) return;

    isCloneThinking = true;
    startReplayClock();
    const thinkStart = Date.now();

    try {
      const oppColor = playerColor === 'white' ? 'black' : 'white';
      const oppName = currentGame.opponent && currentGame.opponent !== 'Opponent Name'
        ? currentGame.opponent
        : 'kovinar';

      const res = await requestCloneMove({
        fen: currentFen,
        opponent_color: oppColor,
        my_clock: currentYouTime,
        opponent_clock: currentThemTime,
        opponent_username: oppName,
        opponent_elo: currentGame.opponent_elo,
        my_elo: currentGame.player_elo,
      });

      // Artificial Delay: simulate realistic human think time like a real clock in replay
      const predictedSeconds = typeof res?.think_time === 'number' && res.think_time > 0
        ? res.think_time
        : 2.2;
      const targetDelayMs = Math.min(Math.max(predictedSeconds * 1000, 1400), 5500);
      const elapsedMs = Date.now() - thinkStart;
      const remainingDelay = Math.max(0, targetDelayMs - elapsedMs);

      if (remainingDelay > 0) {
        await new Promise((resolve) => setTimeout(resolve, remainingDelay));
      }

      if (res && (res.san || res.move || res.uci)) {
        const moveText = res.san || res.move;
        let moved = false;
        if (moveText) {
          try {
            chess.move(moveText);
            moved = true;
          } catch {
            moved = false;
          }
        }
        if (!moved && res.uci && res.uci.length >= 4) {
          try {
            chess.move({
              from: res.uci.slice(0, 2) as any,
              to: res.uci.slice(2, 4) as any,
              promotion: (res.uci[4] || 'q') as any,
            });
            moved = true;
          } catch {}
        }

        if (moved) {
          currentFen = chess.fen();
          moveHistory = chess.history();
          currentMoveIndex = moveHistory.length - 1;
        }

        if (res.opponent_clock != null) {
          replayThemTime = res.opponent_clock;
        }
      }
    } catch (err) {
      console.error('Clone move prediction failed:', err);
    } finally {
      isCloneThinking = false;
    }
  }

  let countdown = $state<number | null>(null);
  let countdownTimer: ReturnType<typeof setInterval> | null = null;

  function startReplayMode() {
    stopAutoPlay();
    viewMode = 'focused';
    replayYouTime = youTime;
    replayThemTime = themTime;

    // Start 3, 2, 1 countdown before starting the game clock
    if (countdownTimer) clearInterval(countdownTimer);
    countdown = 3;

    countdownTimer = setInterval(() => {
      if (countdown !== null && countdown > 1) {
        countdown -= 1;
      } else {
        if (countdownTimer) clearInterval(countdownTimer);
        countdownTimer = null;
        countdown = null;

        // Start clock after countdown finishes
        startReplayClock();
        setTimeout(() => {
          triggerCloneMove();
        }, 350);
      }
    }, 1000);
  }

  function exitReplayMode() {
    if (countdownTimer) {
      clearInterval(countdownTimer);
      countdownTimer = null;
    }
    countdown = null;
    stopReplayClock();
    viewMode = 'expanded';
    replayYouTime = null;
    replayThemTime = null;
    isCloneThinking = false;
  }

  // Game Commentary state (reactive based on current game ply)
  let lastAcknowledgedPivotalId = $state<string | null>(null);

  const gameCommentary = $derived.by<CommentaryMoment>(() => {
    if (backendError) {
      return {
        phase: 'Error',
        headline: 'Model Missing',
        text: backendError,
        isPivotal: true,
        pivotalLabel: 'Error'
      };
    }
    if (isCommentaryLoading) {
      return {
        phase: 'Analyzing',
        headline: 'Coaching Commentary Generating...',
        text: 'Analyzing key turning points, blunder checks, and opening strategy with AI Coach...'
      };
    }

    // Initial position before any moves have been played (currentMoveIndex === -1)
    if (currentMoveIndex < 0) {
      const opp = currentGame.opponent || 'Opponent';
      return {
        phase: 'Game Setup',
        headline: `Match vs ${opp}`,
        text: realNarrative || 'Use the move controls below to step through each position and view coach analysis.'
      };
    }

    const currentPly = currentMoveIndex + 1;

    // Check for commentary generated by AI coach
    if (realCommentary && realCommentary.length > 0) {
      // 1. Direct match on current ply
      const exactMatch = realCommentary.find(
        (c) => (c as any).ply === currentPly || (c as any).ply === currentMoveIndex
      );
      if (exactMatch) {
        return {
          ...exactMatch,
          pivotalId: exactMatch.pivotalId || `moment-${currentPly}`
        };
      }

      // 2. Nearest prior commentary moment up to this ply
      const pastMoments = realCommentary
        .filter((c) => typeof (c as any).ply === 'number' && (c as any).ply <= currentPly)
        .sort((a, b) => ((b as any).ply || 0) - ((a as any).ply || 0));

      if (pastMoments.length > 0) {
        return {
          ...pastMoments[0],
          pivotalId: pastMoments[0].pivotalId || `moment-${(pastMoments[0] as any).ply}`
        };
      }

      // If before the first annotated moment, show opening overview or first moment
      if (realCommentary[0]) {
        return realCommentary[0];
      }
    }

    return {
      phase: 'Coaching',
      headline: realNarrative ? 'Game Narrative' : 'Move Analysis',
      text: realNarrative || 'Step through moves to inspect evaluations and tactical turning points.'
    };
  });

  // Move handling
  function handleMove(move: { from: string; to: string; san: string }) {
    if (viewMode === 'focused' && (isOpponentTurn || isCloneThinking)) {
      return;
    }
    chess.move(move.san);
    currentFen = chess.fen();
    moveHistory = chess.history();
    currentMoveIndex = moveHistory.length - 1;

    // In replay mode, trigger clone move response right after user move!
    if (viewMode === 'focused') {
      setTimeout(() => {
        triggerCloneMove();
      }, 250);
    }
  }

  // Controls mode: 'buttons' (play, forward, backward) vs 'slider' (scrubber)
  let controlsMode = $state<'buttons' | 'slider'>('buttons');

  function toggleControlsMode() {
    controlsMode = controlsMode === 'buttons' ? 'slider' : 'buttons';
  }

  function handleScrubberInput(e: Event) {
    stopAutoPlay();
    const target = e.currentTarget as HTMLInputElement;
    const newIndex = parseInt(target.value, 10);
    jumpToMove(newIndex);
  }

  // Navigation controls
  function stepBackward() {
    stopAutoPlay();
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
    if (currentMoveIndex < samplePgnMoves.length - 1) {
      currentMoveIndex++;
      reconstructFenToIndex(currentMoveIndex);
    }
  }

  function toggleAutoPlay() {
    if (isPlaying) {
      stopAutoPlay();
    } else {
      // If we are at the end, restart from the beginning
      if (currentMoveIndex >= samplePgnMoves.length - 1) {
        currentMoveIndex = -1;
        reconstructFenToIndex(currentMoveIndex);
        lastAcknowledgedPivotalId = null;
      }
      // If resuming from a pivotal moment, acknowledge it so autoplay continues
      if (gameCommentary.isPivotal && gameCommentary.pivotalId) {
        lastAcknowledgedPivotalId = gameCommentary.pivotalId;
      }
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
    stopReplayClock();
    if (countdownTimer) {
      clearInterval(countdownTimer);
      countdownTimer = null;
    }
    countdown = null;
    lastAcknowledgedPivotalId = null;
    chess.reset();
    currentFen = chess.fen();
    moveHistory = [];
    currentMoveIndex = -1;
    replayYouTime = null;
    replayThemTime = null;
    isCloneThinking = false;
  }

  // Moves Modal state and logic
  let showMovesModal = $state(false);
  let movesModalTab = $state<'played' | 'all'>('played');

  function jumpToMove(targetIndex: number) {
    stopAutoPlay();
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
        yourOdds: Math.round(val * 10) / 10,
        theirOdds: Math.round((100 - val) * 10) / 10,
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
    stopReplayClock();
    if (countdownTimer) {
      clearInterval(countdownTimer);
      countdownTimer = null;
    }
  });
</script>

<div class="analysis_page_container">
  <!-- Main Analysis Workspace -->
  <main class="analysis_workspace {viewMode === 'focused' ? 'focused_workspace' : ''}">
    <!-- Left Column: Interactive Chessboard -->
    <section class="board_section">
      <Chessboard
        fen={currentFen}
        onmove={handleMove}
        {viewMode}
        orientation={playerColor}
        interactive={!isCloneThinking && (viewMode !== 'focused' || !isOpponentTurn) && countdown === null}
      />
      {#if countdown !== null}
        <div class="replay_countdown_overlay">
          <div class="countdown_circle">
            <span class="countdown_number">{countdown}</span>
          </div>
        </div>
      {/if}
    </section>

    <!-- Right Column: Interactive Widgets -->
    <section class="widgets_section">
      {#if viewMode === 'expanded'}
        <!-- Replay button at top right of the section, aligned inline with rank 8 of the board -->
        <div class="widgets_header">
          <button
            class="mode_toggle_pill {gameCommentary.isPivotal ? 'pivotal_highlight' : ''}"
            onclick={startReplayMode}
            title={gameCommentary.isPivotal ? 'Pivotal Moment reached! Click to view in Replay mode' : 'Switch to Replay mode'}
            aria-label={gameCommentary.isPivotal ? 'Pivotal Moment reached! Click to view in Replay mode' : 'Switch to Replay mode'}
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
          </button>
        </div>

        {#if backendError}
          <div class="backend_error_banner" role="alert">
            <span class="error_icon">⚠️</span>
            <span>{backendError}</span>
          </div>
        {/if}

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
                <span class="odds_percent">{formatOdds(yourOdds)}%</span>
                <span class="odds_label">Your Odds</span>
              </div>
              <div class="capsule_half gray_half">
                <span class="odds_percent">{formatOdds(theirOdds)}%</span>
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
              {#if samplePgnMoves.length === 0}
                <div class="empty_moves_notice">
                  <span>No moves recorded</span>
                </div>
              {:else}
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
              {/if}
            </div>
          </div>

          <!-- Row 3: Live Commentary Text Box -->
          <div class="widget_box full_width_widget commentary_widget_box">
            <h3 class="widget_heading">Commentary</h3>
            <div class="commentary_card {gameCommentary.isPivotal ? 'pivotal_moment_card' : ''} {isCommentaryLoading ? 'commentary_generating_card' : ''}">
              <div class="commentary_header">
                <div class="commentary_badge_group">
                  <span class="commentary_phase_badge {isCommentaryLoading ? 'generating_phase' : ''}">
                    {#if isCommentaryLoading}
                      <span class="small_spinner"></span>
                    {/if}
                    {gameCommentary.phase}
                  </span>
                  {#if currentMoveIndex >= 0}
                    <span class="commentary_move_badge">
                      Move {Math.floor(currentMoveIndex / 2) + 1}{currentMoveIndex % 2 === 0 ? '.' : '...'} {samplePgnMoves[currentMoveIndex]}
                    </span>
                  {/if}
                </div>
                <div class="commentary_live_indicator">
                  {#if isCommentaryLoading}
                    <span class="generating_badge">
                      <span class="pulse_sparkle">✦</span>
                      <span>AI Generating</span>
                    </span>
                  {:else if gameCommentary.isPivotal}
                    <span class="commentary_pivotal_badge">
                      ⚡ Pivotal Moment
                    </span>
                  {:else}
                    <span class="commentary_pulse_dot"></span>
                    <span>Live Analysis</span>
                  {/if}
                </div>
              </div>

              <h4 class="commentary_headline">
                {#if isCommentaryLoading}
                  <span class="shimmer_headline">{gameCommentary.headline}</span>
                {:else}
                  {gameCommentary.headline}
                {/if}
              </h4>
              <p class="commentary_text {isCommentaryLoading ? 'generating_text' : ''}">{gameCommentary.text}</p>
            </div>
          </div>
        </div>

      {:else}
        <!-- FOCUSED ANALYSIS VIEW (focused_analysis_page.png) -->
        <div class="focused_container">
          <div class="player_info_card top_player {isCloneThinking ? 'is_thinking' : ''}">
            <h2 class="player_display_name">
              {currentGame.opponent}
              {#if isCloneThinking}
                <span class="thinking_badge">Thinking...</span>
              {/if}
            </h2>
            <div class="player_stats_row">
              {#if currentGame.opponent_elo != null}
                <span class="stat_badge" title="Opponent Elo Rating">
                  <img src="/chess_icon.svg" alt="Chess.com" class="rating_chess_logo" />
                  {currentGame.opponent_elo}
                </span>
              {/if}
              {#if currentGame.time_control}
                <span class="stat_badge" title="Time Control">
                  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="9"/>
                    <polyline points="12 6 12 12 16 14"/>
                  </svg>
                  {Math.floor(parseInt(currentGame.time_control) / 60)} min
                </span>
              {/if}
            </div>
          </div>

          <!-- Middle Clock Widget (split capsule matching the concept mockup) -->
          <div class="focused_clock_section">
            <div class="split_capsule clock_capsule focused_clock_capsule">
              <div class="capsule_half black_half">
                <span class="clock_digits">{formatTime(currentYouTime)}</span>
              </div>
              <div class="capsule_half gray_half">
                <span class="clock_digits">{formatTime(currentThemTime)}</span>
              </div>
            </div>
          </div>

          <div class="player_info_card bottom_player">
            <h2 class="player_display_name">You</h2>
            <div class="player_stats_row">
              {#if currentGame.player_elo != null}
                <span class="stat_badge" title="Your Elo Rating">
                  <img src="/chess_icon.svg" alt="Chess.com" class="rating_chess_logo" />
                  {currentGame.player_elo}
                </span>
              {/if}
              {#if currentGame.time_control}
                <span class="stat_badge" title="Time Control">
                  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="9"/>
                    <polyline points="12 6 12 12 16 14"/>
                  </svg>
                  {Math.floor(parseInt(currentGame.time_control) / 60)} min
                </span>
              {/if}
            </div>
          </div>
        </div>
      {/if}
    </section>
  </main>

  {#if viewMode === 'focused'}
    <!-- Restart button in bottom right corner (matching focused_analysis_page.png) -->
    <div class="focused_bottom_bar">
      <button class="restart_pill_btn" onclick={() => { restartGame(); exitReplayMode(); }}>
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
                <span class="hud_value your_val">{formatOdds(activeInspectPoint.yourOdds)}%</span>
              </div>
              <div class="hud_divider"></div>
              <div class="hud_item">
                <span class="hud_label">Their Odds</span>
                <span class="hud_value their_val">{formatOdds(activeInspectPoint.theirOdds)}%</span>
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
                  aria-label="Move {pt.moveNumber} {pt.color}: {formatOdds(pt.yourOdds)}% win odds"
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

  .backend_error_banner {
    display: flex;
    align-items: center;
    gap: 0.65rem;
    padding: 0.85rem 1.15rem;
    background: #fef2f2;
    border: 1.5px solid #ef4444;
    color: #991b1b;
    border-radius: 14px;
    font-size: 13.5px;
    font-weight: 600;
    margin-bottom: 0.85rem;
  }

  .backend_error_banner .error_icon {
    font-size: 16px;
    flex-shrink: 0;
  }

  .thinking_badge {
    display: inline-flex;
    align-items: center;
    font-size: 12px;
    font-weight: 700;
    color: var(--accent-1, #e8590c);
    background: rgba(232, 89, 12, 0.12);
    border: 1px solid rgba(232, 89, 12, 0.3);
    padding: 2px 8px;
    border-radius: 8px;
    margin-left: 10px;
    vertical-align: middle;
    animation: thinkingPulse 1.4s ease-in-out infinite alternate;
  }

  @keyframes thinkingPulse {
    0% { opacity: 0.6; transform: scale(0.97); }
    100% { opacity: 1; transform: scale(1.02); }
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
    position: relative;
    flex: 0 0 580px;
    max-width: 580px;
    width: 100%;
    display: flex;
    justify-content: center;
  }

  /* Replay Countdown Overlay */
  .replay_countdown_overlay {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.45);
    backdrop-filter: blur(2px);
    border-radius: 12px;
    z-index: 50;
    pointer-events: all;
    animation: fadeInCountdown 0.2s ease-out;
  }

  .countdown_circle {
    width: 110px;
    height: 110px;
    border-radius: 50%;
    background: #ffffff;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35), 0 0 0 6px rgba(232, 89, 12, 0.4);
    display: flex;
    align-items: center;
    justify-content: center;
    animation: popScaleCountdown 0.85s cubic-bezier(0.34, 1.56, 0.64, 1) infinite;
  }

  .countdown_number {
    font-size: 58px;
    font-weight: 900;
    color: #e8590c;
    line-height: 1;
    user-select: none;
  }

  @keyframes popScaleCountdown {
    0% { transform: scale(0.6); opacity: 0.7; }
    50% { transform: scale(1.08); opacity: 1; }
    100% { transform: scale(0.95); opacity: 0.9; }
  }

  @keyframes fadeInCountdown {
    from { opacity: 0; }
    to { opacity: 1; }
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

  .empty_moves_notice {
    width: 100%;
    text-align: center;
    font-size: 13.5px;
    font-weight: 600;
    color: #4b5563;
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

  .commentary_card.commentary_generating_card {
    border: 1.5px solid rgba(139, 92, 246, 0.4);
    background: linear-gradient(135deg, rgba(245, 243, 255, 0.85) 0%, rgba(255, 255, 255, 0.98) 100%);
    box-shadow: 0 4px 18px rgba(139, 92, 246, 0.08);
  }

  .generating_phase {
    background: #ede9fe !important;
    color: #6d28d9 !important;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }

  .small_spinner {
    width: 10px;
    height: 10px;
    border: 2px solid rgba(109, 40, 217, 0.25);
    border-top-color: #6d28d9;
    border-radius: 50%;
    animation: spin-commentary 0.8s linear infinite;
    display: inline-block;
  }

  .generating_badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 10px;
    border-radius: 12px;
    background: #f5f3ff;
    color: #7c3aed;
    font-size: 11px;
    font-weight: 700;
    border: 1px solid #ddd6fe;
  }

  .pulse_sparkle {
    display: inline-block;
    animation: pulse-sparkle 1.4s ease-in-out infinite;
    color: #8b5cf6;
  }

  .shimmer_headline {
    background: linear-gradient(90deg, #4c1d95 0%, #7c3aed 50%, #4c1d95 100%);
    background-size: 200% auto;
    color: transparent;
    -webkit-background-clip: text;
    background-clip: text;
    animation: shimmer-text 2s linear infinite;
  }

  .generating_text {
    color: #6b7280;
    font-style: italic;
  }

  @keyframes spin-commentary {
    to { transform: rotate(360deg); }
  }

  @keyframes pulse-sparkle {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.4; transform: scale(0.85); }
  }

  @keyframes shimmer-text {
    to { background-position: 200% center; }
  }

  .commentary_pivotal_badge {
    font-size: 11px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    background: #ec5d0b;
    color: #ffffff;
    padding: 0.25rem 0.75rem;
    border-radius: 9999px;
    box-shadow: none;
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    line-height: 1.2;
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
    align-items: flex-start;
    gap: 3.5rem;
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
    width: 320px;
    min-width: 320px;
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

  .rating_chess_logo {
    width: 17px;
    height: 17px;
    object-fit: contain;
    border-radius: 4px;
    display: inline-block;
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
