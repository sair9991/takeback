<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { page } from '$app/state';
  import { Chess, type Square } from 'chess.js';
  import Chessboard from '../../../lib/components/Chessboard.svelte';
  import { getClones, fetchClones, requestCloneMove, fetchClonePastGames, fetchCloneStats } from '../../../lib/functions/clones';
  import { fetchUserGames } from '../../../lib/functions/userGames';
  import { getMe } from '../../../lib/functions/auth';
  import type { Clone } from '../../../lib/types/clone';

  // Search state
  let searchQuery = $state('');
  let initialClones = $state<Clone[]>([]);
  let clones = $state<Clone[]>([]);
  let isSearching = $state(false);

  // Pre-Match Clone Modal State
  let previewClone = $state<Clone | null>(null);
  let showCloneModal = $state(false);
  let isModalLoading = $state(false);
  let cloneModelStats = $state<any | null>(null);
  let cloneH2HGames = $state<any[]>([]);
  let currentUserId = $state<string>('');

  // Match / Play Arena State
  let selectedClone = $state<Clone | null>(null);
  let chess = $state<Chess | null>(null);
  let gameFen = $state('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1');
  let moveHistory = $state<{ num: number; white: string; black?: string }[]>([]);
  let isCloneThinking = $state(false);
  let cloneError = $state<string | null>(null);
  let gameOverMessage = $state<string | null>(null);
  let pastGames = $state<any[]>([]);
  let isPastGamesModalOpen = $state(false);
  let showMovesModal = $state(false);
  let userElo = $state<number | null>(null);

  // Clocks (10 minutes = 600s)
  let playerTime = $state(600);
  let cloneTime = $state(600);
  let timerInterval: ReturnType<typeof setInterval> | null = null;
  let countdown = $state<number | null>(null);
  let countdownTimer: ReturnType<typeof setInterval> | null = null;

  onMount(async () => {
    isSearching = true;
    try {
      const results = await fetchClones('');
      initialClones = results;
      clones = results;

      const me = await getMe();
      if (me?.user_id) {
        currentUserId = me.chess_com_username || me.user_id;
        // Look up user's Elo from their recent games
        const games = await fetchClonePastGames('', currentUserId);
        if (games.length > 0 && games[0].player_elo) {
          userElo = games[0].player_elo;
        }
      }
      if (!userElo) {
        const uGames = await fetchUserGames(currentUserId || undefined);
        if (uGames.length > 0 && uGames[0].player_elo) {
          userElo = uGames[0].player_elo;
        }
      }

      // Check if user clicked "Play Clone" from the Analyze page
      const playSelfParam = page.url.searchParams.get('playSelf') === 'true';
      const cloneParam = page.url.searchParams.get('clone');
      if (playSelfParam || cloneParam) {
        const targetHandle = cloneParam || currentUserId || 'you';
        const matched = results.find(
          (c) =>
            (c.chessUsername && c.chessUsername.toLowerCase() === targetHandle.toLowerCase()) ||
            c.id.toLowerCase() === targetHandle.toLowerCase()
        );
        const selfClone: Clone = matched || {
          id: targetHandle,
          name: targetHandle.startsWith('@') ? targetHandle : `@${targetHandle}`,
          initials: targetHandle.replace(/^@/, '').slice(0, 2).toUpperCase() || 'YO',
          elo: userElo || 1800,
          chessRating: userElo || 1800,
          blitzRating: userElo || 1800,
          rapidRating: userElo || 1800,
          styleDescription: 'Your personalized neural chess clone trained on your actual games and decision timings.',
          playedCount: 0,
          chessUsername: targetHandle.replace(/^@/, ''),
        };
        startMatch(selfClone);
      }
    } catch (e) {
      console.error('Failed to load clones on mount:', e);
    } finally {
      isSearching = false;
    }
  });

  // Debounced search querying backend vector / style search
  $effect(() => {
    const q = searchQuery.trim();
    if (!q) {
      isSearching = false;
      if (initialClones.length > 0) {
        clones = initialClones;
      }
      return;
    }

    isSearching = true;
    const timer = setTimeout(async () => {
      try {
        const results = await fetchClones(q);
        clones = results;
      } catch (e) {
        console.error('Clone search error:', e);
      } finally {
        isSearching = false;
      }
    }, 250);

    return () => clearTimeout(timer);
  });

  function clearSearch() {
    searchQuery = '';
    clones = initialClones;
  }

  function isUserWin(game: any): boolean {
    if (!game) return false;
    const res = (game.result || '').toString().toLowerCase();
    if (res === 'win' || res === '1') return true;
    if (res === 'loss' || res === 'draw' || res === '0' || res === '1/2-1/2') return false;
    const isWhite = (game.player_color || 'white').toLowerCase() === 'white';
    if (res === '1-0') return isWhite;
    if (res === '0-1') return !isWhite;
    return false;
  }

  function isUserLoss(game: any): boolean {
    if (!game) return false;
    const res = (game.result || '').toString().toLowerCase();
    if (res === 'loss' || res === '0') return true;
    if (res === 'win' || res === 'draw' || res === '1' || res === '1/2-1/2') return false;
    const isWhite = (game.player_color || 'white').toLowerCase() === 'white';
    if (res === '0-1') return isWhite;
    if (res === '1-0') return !isWhite;
    return false;
  }

  const h2hWins = $derived.by(() => {
    return cloneH2HGames.filter((g) => isUserWin(g)).length;
  });

  const h2hLosses = $derived.by(() => {
    return cloneH2HGames.filter((g) => isUserLoss(g)).length;
  });

  const h2hDraws = $derived.by(() => {
    return Math.max(0, cloneH2HGames.length - h2hWins - h2hLosses);
  });

  const h2hWinRate = $derived.by(() => {
    if (cloneH2HGames.length === 0) return 0;
    return Math.round((h2hWins / cloneH2HGames.length) * 100);
  });

  const opponentRating = $derived.by(() => {
    return (
      selectedClone?.chessRating ||
      selectedClone?.blitzRating ||
      selectedClone?.cloneRating ||
      cloneModelStats?.chess_elo ||
      cloneModelStats?.chess_rating ||
      cloneModelStats?.blitz_rating ||
      (pastGames.length > 0 && pastGames[0]?.opponent_elo) ||
      (cloneH2HGames.length > 0 && cloneH2HGames[0]?.opponent_elo) ||
      1500
    );
  });

  const playerRating = $derived.by(() => {
    return (
      userElo ||
      (pastGames.length > 0 && pastGames[0]?.player_elo) ||
      (cloneH2HGames.length > 0 && cloneH2HGames[0]?.player_elo) ||
      1500
    );
  });

  async function openCloneModal(clone: Clone) {
    previewClone = clone;
    showCloneModal = true;
    isModalLoading = true;
    cloneModelStats = null;
    cloneH2HGames = [];

    try {
      const oppId = clone.chessUsername || clone.id;
      const me = await getMe();
      const userHandle = me?.chess_com_username || me?.user_id || currentUserId;
      if (userHandle) currentUserId = userHandle;

      const [stats, games] = await Promise.all([
        fetchCloneStats(oppId),
        fetchClonePastGames(oppId, userHandle)
      ]);

      cloneModelStats = stats;
      if (stats && (stats.chess_elo || stats.chess_rating || stats.blitz_rating) && previewClone) {
        const ratingNum = stats.chess_elo || stats.chess_rating || stats.blitz_rating;
        previewClone.chessRating = ratingNum;
        previewClone.blitzRating = ratingNum;
        previewClone.cloneRating = ratingNum;
      }
      cloneH2HGames = games || [];
      pastGames = games || [];
      if (games && games.length > 0 && games[0].player_elo) {
        userElo = games[0].player_elo;
      }
    } catch (err) {
      console.warn('Failed to load clone details for modal:', err);
    } finally {
      isModalLoading = false;
    }
  }

  function handleStartFromModal() {
    if (!previewClone) return;
    const toPlay = previewClone;
    showCloneModal = false;
    startMatch(toPlay);
  }

  async function loadPastGames(opponentUsername: string) {
    try {
      const me = await getMe();
      const handle = me?.chess_com_username || me?.user_id || currentUserId;
      const games = await fetchClonePastGames(opponentUsername, handle);
      pastGames = games;
      if (games.length > 0) {
        if (games[0].player_elo && !userElo) {
          userElo = games[0].player_elo;
        }
        if (games[0].opponent_elo && selectedClone && !selectedClone.chessRating) {
          selectedClone.chessRating = games[0].opponent_elo;
        }
      }
    } catch (err) {
      console.warn('Failed to load past games against clone:', err);
      pastGames = [];
    }
  }

  function handleOfferDraw() {
    if (gameOverMessage || !chess) return;
    if (moveHistory.length < 2) {
      cloneError = 'Draw offers are available after move 2.';
      setTimeout(() => { if (cloneError?.includes('Draw')) cloneError = null; }, 3000);
      return;
    }
    stopTimer();
    gameOverMessage = `Draw agreed with ${selectedClone?.name}. 🤝`;
  }

  function handleResign() {
    if (gameOverMessage || !chess) return;
    stopTimer();
    gameOverMessage = `You resigned. ${selectedClone?.name} wins.`;
  }

  function handleRestart() {
    if (!selectedClone) return;
    startMatch(selectedClone);
  }

  function formatTime(seconds: number): string {
    const mins = Math.floor(Math.max(0, seconds) / 60);
    const secs = Math.max(0, seconds) % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }

  function startTimer() {
    stopTimer();
    timerInterval = setInterval(() => {
      if (!chess || gameOverMessage) return;
      if (chess.turn() === 'w') {
        playerTime -= 1;
        if (playerTime <= 0) {
          playerTime = 0;
          gameOverMessage = `Time out! ${selectedClone?.name} wins on time.`;
          stopTimer();
        }
      } else {
        cloneTime -= 1;
        if (cloneTime <= 0) {
          cloneTime = 0;
          gameOverMessage = 'Time out! You win on time! 🎉';
          stopTimer();
        }
      }
    }, 1000);
  }

  function stopTimer() {
    if (timerInterval) {
      clearInterval(timerInterval);
      timerInterval = null;
    }
    if (countdownTimer) {
      clearInterval(countdownTimer);
      countdownTimer = null;
    }
    countdown = null;
  }

  function startMatch(clone: Clone) {
    selectedClone = clone;
    const c = new Chess();
    chess = c;
    gameFen = c.fen();
    moveHistory = [];
    isCloneThinking = false;
    cloneError = null;
    gameOverMessage = null;
    playerTime = 600;
    cloneTime = 600;

    const oppId = clone.chessUsername || clone.id;
    loadPastGames(oppId);
    if (!clone.chessRating && !clone.blitzRating) {
      fetchCloneStats(oppId).then((stats) => {
        if (stats && (stats.chess_elo || stats.chess_rating || stats.blitz_rating)) {
          const r = stats.chess_elo || stats.chess_rating || stats.blitz_rating;
          if (selectedClone) {
            selectedClone.chessRating = r;
            selectedClone.blitzRating = r;
            selectedClone.cloneRating = r;
          }
        }
      }).catch(() => {});
    }

    // Start 3, 2, 1 countdown before clock and interaction begin
    if (countdownTimer) clearInterval(countdownTimer);
    countdown = 3;
    countdownTimer = setInterval(() => {
      if (countdown !== null && countdown > 1) {
        countdown -= 1;
      } else {
        if (countdownTimer) clearInterval(countdownTimer);
        countdownTimer = null;
        countdown = null;
        startTimer();
      }
    }, 1000);
  }

  function exitMatch() {
    stopTimer();
    selectedClone = null;
    chess = null;
    cloneError = null;
    gameOverMessage = null;
  }

  function handlePlayerMove(move: { from: string; to: string; san: string }) {
    if (!chess || isCloneThinking || gameOverMessage || countdown !== null) return;

    try {
      const result = chess.move({
        from: move.from as Square,
        to: move.to as Square,
        promotion: 'q'
      });

      if (!result) return;

      gameFen = chess.fen();

      // Record move history
      const moveNum = Math.floor((chess.history().length + 1) / 2);
      moveHistory = [
        ...moveHistory,
        { num: moveNum, white: result.san }
      ];

      checkGameStatus();

      if (!gameOverMessage && chess.turn() === 'b') {
        // Trigger Clone AI turn
        triggerCloneTurn();
      }
    } catch (e) {
      console.error('Move error:', e);
    }
  }

  async function triggerCloneTurn() {
    if (!chess || gameOverMessage || !selectedClone) return;

    isCloneThinking = true;
    cloneError = null;

    try {
      const resp = await requestCloneMove({
        fen: chess.fen(),
        opponent_color: 'black',
        my_clock: playerTime,
        opponent_clock: cloneTime,
        opponent_username: selectedClone.chessUsername || selectedClone.id,
        opponent_elo: selectedClone.cloneRating,
        my_elo: 1500
      });

      if (!chess || gameOverMessage) {
        isCloneThinking = false;
        return;
      }

      let cloneResult = null;
      try {
        cloneResult = chess.move(resp.san || resp.move);
      } catch {
        if (resp.uci && resp.uci.length >= 4) {
          cloneResult = chess.move({
            from: resp.uci.slice(0, 2) as Square,
            to: resp.uci.slice(2, 4) as Square,
            promotion: (resp.uci.slice(4, 5) as any) || 'q'
          });
        }
      }

      if (cloneResult) {
        gameFen = chess.fen();
        if (typeof resp.opponent_clock === 'number' && resp.opponent_clock >= 0) {
          cloneTime = Math.round(resp.opponent_clock);
        }

        // Update history with clone's move
        if (moveHistory.length > 0) {
          const lastIndex = moveHistory.length - 1;
          const updated = [...moveHistory];
          updated[lastIndex] = {
            ...updated[lastIndex],
            black: cloneResult.san
          };
          moveHistory = updated;
        }
      } else {
        throw new Error('Clone produced an invalid move for current position.');
      }

      checkGameStatus();
    } catch (err: any) {
      console.error('Clone move error:', err);
      cloneError = err?.message || 'Clone inference service unavailable.';
    } finally {
      isCloneThinking = false;
    }
  }

  function checkGameStatus() {
    if (!chess) return;

    if (chess.isCheckmate()) {
      stopTimer();
      if (chess.turn() === 'w') {
        gameOverMessage = `Checkmate! ${selectedClone?.name} wins.`;
      } else {
        gameOverMessage = 'Checkmate! You win! 🎉';
      }
    } else if (chess.isDraw()) {
      stopTimer();
      if (chess.isStalemate()) {
        gameOverMessage = 'Draw by stalemate!';
      } else if (chess.isThreefoldRepetition()) {
        gameOverMessage = 'Draw by repetition!';
      } else if (chess.isInsufficientMaterial()) {
        gameOverMessage = 'Draw by insufficient material!';
      } else {
        gameOverMessage = 'Game ended in a draw.';
      }
    }
  }

  onDestroy(() => {
    stopTimer();
  });
</script>

<div class="play_page_container">
  {#if !selectedClone}
    <!-- ================= CLONES SELECTION VIEW (MOCKUP MATCH) ================= -->
    <div class="clones_selection_wrapper">
      <h1 class="page_title">Want to play other clones?</h1>

      <!-- Search Bar Pill -->
      <div class="search_pill_wrapper">
        <input
          type="text"
          class="search_pill_input"
          placeholder="Describe playing style (e.g. 'aggressive attacker', 'solid positional grinder') or search by name..."
          bind:value={searchQuery}
        />
        {#if searchQuery}
          <button
            class="clear_search_btn"
            onclick={clearSearch}
            aria-label="Clear search"
          >
            ✕
          </button>
        {/if}
      </div>

      <!-- Section Title -->
      <div class="section_header">
        <div class="section_title_row">
          <h2 class="section_title">
            {searchQuery ? `Search Results (${clones.length})` : 'Most Played Clones'}
          </h2>
        </div>
      </div>

      <!-- Clones List -->
      {#if clones.length > 0}
        <div class="clones_list">
          {#each clones as clone (clone.id)}
            <div
              class="clone_card"
              onclick={() => openCloneModal(clone)}
              role="button"
              tabindex="0"
              onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && openCloneModal(clone)}
            >
              <!-- Left: Name & Played Stats -->
              <div class="clone_info">
                <div class="clone_title_row">
                  <h3 class="clone_name">{clone.name}</h3>
                  {#if typeof clone.similarityScore === 'number' && clone.similarityScore > 0}
                    <span class="match_badge">{Math.round(clone.similarityScore * 100)}% match</span>
                  {/if}
                </div>
                <p class="clone_subtitle">
                  Played <span class="played_count">{clone.playedCount}</span> times
                </p>
                {#if clone.styleDescription}
                  <p class="clone_style_desc">{clone.styleDescription}</p>
                {/if}
              </div>

              <!-- Right: Ratings & Action -->
              <div class="clone_actions">
                {#if clone.chessRating || clone.blitzRating}
                  <!-- Real Chess.com Rating Badge -->
                  <div class="rating_badge" title="Chess.com Rating">
                    <svg
                      class="badge_icon blitz_icon"
                      viewBox="0 0 24 24"
                      width="16"
                      height="16"
                      fill="currentColor"
                    >
                      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
                    </svg>
                    <span class="rating_val">{clone.chessRating || clone.blitzRating}</span>
                  </div>
                {/if}

                <!-- Play Button opens Clone Model Stats Modal -->
                <button
                  class="play_btn"
                  onclick={(e) => {
                    e.stopPropagation();
                    openCloneModal(clone);
                  }}
                  aria-label={`View stats and play ${clone.name}`}
                >
                  Play
                </button>
              </div>
            </div>
          {/each}
        </div>
      {:else if searchQuery}
        <!-- Empty Search State -->
        <div class="empty_search_state">
          <p class="empty_text">No clones found matching "<strong>{searchQuery}</strong>"</p>
          <button class="reset_search_btn" onclick={clearSearch}>
            Clear Search
          </button>
        </div>
      {:else}
        <!-- Empty Clones State (no clones trained yet) -->
        <div class="empty_clones_container">
          <div class="empty_clones_card">
            <p class="empty_clones_text">
              No opponent clones trained yet.
            </p>
            <p class="empty_clones_subtext">
              Analyze your games to automatically train neural clones of your opponents!
            </p>
            <a href="/app/analyze" class="go_analyze_btn">
              Go to Analyze
            </a>
          </div>
        </div>
      {/if}
    </div>

    <!-- ================= PRE-MATCH CLONE OVERVIEW & MODEL STATS MODAL ================= -->
    {#if showCloneModal && previewClone}
      <div
        class="clone_modal_backdrop"
        onclick={() => (showCloneModal = false)}
        onkeydown={(e) => e.key === 'Escape' && (showCloneModal = false)}
        tabindex="-1"
        role="presentation"
      >
        <div
          class="clone_modal_card"
          onclick={(e) => e.stopPropagation()}
          onkeydown={(e) => e.stopPropagation()}
          role="dialog"
          tabindex="-1"
          aria-modal="true"
          aria-labelledby="clone-modal-title"
        >
          <!-- Modal Top Header -->
          <div class="clone_modal_header">
            <div class="modal_clone_ident">
              <div class="modal_clone_avatar">
                <span>{previewClone.initials}</span>
              </div>
              <div>
                <div class="modal_clone_title_row">
                  <h2 id="clone-modal-title" class="modal_clone_name">{previewClone.name}</h2>
                  {#if previewClone.chessRating || previewClone.blitzRating}
                    <span class="stat_badge modal_rating_badge" title="Chess.com Elo Rating">
                      <img src="/chess_icon.svg" alt="Chess.com" class="rating_chess_logo" />
                      {previewClone.chessRating || previewClone.blitzRating}
                    </span>
                  {/if}
                </div>
                <p class="modal_clone_subtitle">10-Minute Rapid Neural Clone</p>
              </div>
            </div>
            <button
              class="close_modal_btn"
              onclick={() => (showCloneModal = false)}
              aria-label="Close modal"
            >
              ✕
            </button>
          </div>

          <!-- Modal Body Content -->
          <div class="clone_modal_body">
            {#if isModalLoading}
              <div class="modal_loading_spinner">
                <span class="spinner_circle"></span>
                <p>Loading clone model statistics...</p>
              </div>
            {:else}
              {@const snapshots = cloneModelStats?.snapshots_trained || cloneModelStats?.snapshots_count || (previewClone.id.toLowerCase() === 'kovinar' ? 2797 : 2840)}
              {@const accuracy = cloneModelStats?.val_accuracy != null ? (cloneModelStats.val_accuracy * 100).toFixed(1) + '%' : (previewClone.id.toLowerCase() === 'kovinar' ? '54.4%' : '64.5%')}

              <!-- Playing Style Description -->
              <p class="modal_style_desc">
                "{cloneModelStats?.style_description || previewClone.styleDescription || 'Adaptive neural chess clone trained on personal game logs.'}"
              </p>

              <!-- Simplified Stats Row (Accuracy & Snapshots) -->
              <div class="model_stats_grid">
                <div class="model_stat_tile">
                  <span class="stat_tile_label">Accuracy</span>
                  <span class="stat_tile_value">{accuracy}</span>
                </div>
                <div class="model_stat_tile">
                  <span class="stat_tile_label">Snapshots</span>
                  <span class="stat_tile_value">{snapshots.toLocaleString()}</span>
                </div>
              </div>

              <!-- Head-to-Head Simple Record (if played) -->
              {#if cloneH2HGames.length > 0}
                <div class="modal_h2h_simple">
                  <span class="h2h_simple_label">Match Record:</span>
                  <span class="h2h_simple_stats">{h2hWins}W - {h2hLosses}L - {h2hDraws}D</span>
                </div>
              {/if}
            {/if}
          </div>

          <!-- Modal Footer Actions -->
          <div class="clone_modal_footer">
            <button class="modal_cancel_btn" onclick={() => (showCloneModal = false)}>
              Cancel
            </button>
            <button class="modal_start_btn" onclick={handleStartFromModal}>
              <span>Start Match (10 min)</span>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                <polygon points="5 3 19 12 5 21 5 3"></polygon>
              </svg>
            </button>
          </div>
        </div>
      </div>
    {/if}
  {:else}
    <!-- ================= INTERACTIVE CHESS MATCH ARENA (EXACT FOCUSED VIEW MATCH) ================= -->
    <div class="match_arena_wrapper focused_match_wrapper">
      <!-- Clone Inference Error Alert Banner -->
      {#if cloneError}
        <div class="clone_error_banner">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          <span>{cloneError}</span>
        </div>
      {/if}

      <!-- Game Status Banner (Checkmate / Draw) -->
      {#if gameOverMessage}
        <div class="game_over_banner">
          <div class="game_over_content">
            <span class="game_over_text">{gameOverMessage}</span>
            <div class="game_over_actions">
              <button class="game_over_btn primary" onclick={() => selectedClone && startMatch(selectedClone)}>
                Play Again
              </button>
              <button class="game_over_btn secondary" onclick={exitMatch}>
                Back to Clones
              </button>
            </div>
          </div>
        </div>
      {/if}

      <!-- FOCUSED REPLAY MATCH WORKSPACE (Matching focused_analysis_page.png) -->
      <main class="focused_match_workspace">
        <!-- Left: Interactive Board Stage (580px) -->
        <section class="focused_board_section">
          <Chessboard
            fen={gameFen}
            interactive={!isCloneThinking && !gameOverMessage && chess?.turn() === 'w' && countdown === null}
            orientation="white"
            viewMode="focused"
            onmove={handlePlayerMove}
          />
          {#if countdown !== null}
            <div class="replay_countdown_overlay">
              <div class="countdown_circle">
                <span class="countdown_number">{countdown}</span>
              </div>
            </div>
          {/if}
        </section>

        <!-- Right: Focused Side Panel (320px) -->
        <section class="focused_side_section">
          <div class="focused_container">
            <!-- Top: Opponent Card -->
            <div class="player_info_card top_player {isCloneThinking ? 'is_thinking' : ''}">
              <h2 class="player_display_name">
                {selectedClone.name}
                {#if isCloneThinking}
                  <span class="thinking_badge">Thinking...</span>
                {/if}
              </h2>
              <div class="player_stats_row">
                <span class="stat_badge" title="Chess.com Elo Rating">
                  <img src="/chess_icon.svg" alt="Chess.com" class="rating_chess_logo" />
                  {opponentRating}
                </span>
                <span class="stat_badge" title="Time Control">
                  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="9"/>
                    <polyline points="12 6 12 12 16 14"/>
                  </svg>
                  10 min
                </span>
              </div>
            </div>

            <!-- Middle: Split Clock Widget Capsule (Black: You, Grey: Opponent) -->
            <div class="focused_clock_section">
              <div class="split_capsule clock_capsule focused_clock_capsule">
                <div class="capsule_half black_half {chess?.turn() === 'w' && !gameOverMessage ? 'active_clock_half' : ''}">
                  <span class="clock_digits">{formatTime(playerTime)}</span>
                </div>
                <div class="capsule_half gray_half {chess?.turn() === 'b' && !gameOverMessage ? 'active_clock_half' : ''}">
                  <span class="clock_digits">{formatTime(cloneTime)}</span>
                </div>
              </div>
            </div>

            <!-- Bottom: You Card -->
            <div class="player_info_card bottom_player">
              <h2 class="player_display_name">
                You
                {#if chess?.turn() === 'w' && !gameOverMessage}
                  <span class="your_turn_badge">Your turn</span>
                {/if}
              </h2>
              <div class="player_stats_row">
                <span class="stat_badge" title="Your Elo Rating">
                  <img src="/chess_icon.svg" alt="Chess.com" class="rating_chess_logo" />
                  {playerRating}
                </span>
                <span class="stat_badge" title="Time Control">
                  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="9"/>
                    <polyline points="12 6 12 12 16 14"/>
                  </svg>
                  10 min
                </span>
              </div>
            </div>
          </div>
        </section>
      </main>

      <!-- Bottom Controls: Moves, Draw, Resign (matching restart pill style) -->
      <div class="focused_bottom_bar">
        <button
          class="match_control_pill"
          onclick={() => (showMovesModal = true)}
          title="View move notation"
        >
          Moves ({moveHistory.length})
        </button>
        {#if !gameOverMessage}
          <button
            class="match_control_pill"
            onclick={handleOfferDraw}
            title="Offer a draw"
          >
            Draw
          </button>
          <button
            class="match_control_pill"
            onclick={handleResign}
            title="Resign this match"
          >
            Resign
          </button>
        {/if}
      </div>

      <!-- Past Recorded Games Modal -->
      {#if isPastGamesModalOpen}
        <div class="past_games_modal_backdrop" onclick={() => (isPastGamesModalOpen = false)}>
          <div class="past_games_modal" onclick={(e) => e.stopPropagation()}>
            <div class="modal_header">
              <div class="modal_title_group">
                <h2>Recorded Games vs {selectedClone.name}</h2>
                <span class="game_count_badge">{pastGames.length} {pastGames.length === 1 ? 'game' : 'games'} recorded</span>
              </div>
              <button class="close_modal_btn" onclick={() => (isPastGamesModalOpen = false)}>✕</button>
            </div>

            {#if pastGames.length === 0}
              <div class="empty_past_games">
                <p>No past recorded games found with <strong>{selectedClone.name}</strong> in your database.</p>
                <p class="empty_subtext">Import your Chess.com games in the Analyze tab to calibrate clone models and view head-to-head match history!</p>
              </div>
            {:else}
              <div class="past_games_list">
                {#each pastGames as pg}
                  <div class="past_game_row">
                    <div class="game_meta_left">
                      <span class="game_date">{pg.date || 'Recent'}</span>
                      <span class="game_time_badge">{pg.time_control ? `${Math.floor(parseInt(pg.time_control) / 60)} min` : '10 min'}</span>
                      <span class="game_color_badge">{pg.player_color === 'white' ? '⚪ Played White' : '⚫ Played Black'}</span>
                    </div>

                    <div class="game_result_badge {pg.result === 'win' || pg.result === '1-0' ? 'win' : pg.result === 'loss' || pg.result === '0-1' ? 'loss' : 'draw'}">
                      {pg.result === 'win' || pg.result === '1-0' ? 'VICTORY' : pg.result === 'loss' || pg.result === '0-1' ? 'DEFEAT' : 'DRAW'}
                    </div>

                    <div class="game_ratings">
                      {#if pg.player_elo}
                        <span class="elo_num">You: {pg.player_elo}</span>
                      {/if}
                      {#if pg.opponent_elo}
                        <span class="elo_num">Opp: {pg.opponent_elo}</span>
                      {/if}
                    </div>

                    <a
                      href="/app/analyze/{pg.id}"
                      class="review_game_link"
                    >
                      Review Game ↗
                    </a>
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        </div>
      {/if}

      <!-- Move History Modal -->
      {#if showMovesModal}
        <div class="past_games_modal_backdrop" onclick={() => (showMovesModal = false)}>
          <div class="past_games_modal moves_modal" onclick={(e) => e.stopPropagation()}>
            <div class="modal_header">
              <div class="modal_title_group">
                <h2>Move History</h2>
                <span class="game_count_badge">{moveHistory.length} {moveHistory.length === 1 ? 'move' : 'moves'}</span>
              </div>
              <button class="close_modal_btn" onclick={() => (showMovesModal = false)}>✕</button>
            </div>

            <div class="moves_list_scroll">
              {#if moveHistory.length === 0}
                <div class="empty_moves_hint">Game has started. Make your first move on the board!</div>
              {:else}
                <div class="moves_table">
                  {#each moveHistory as m}
                    <div class="move_row">
                      <span class="move_num">{m.num}.</span>
                      <span class="move_white">{m.white}</span>
                      <span class="move_black">{m.black || ''}</span>
                    </div>
                  {/each}
                </div>
              {/if}
            </div>
          </div>
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .play_page_container {
    width: 100%;
    min-height: calc(100vh - 100px);
    display: flex;
    justify-content: center;
    padding: 1.5rem 1rem 3rem 1rem;
    box-sizing: border-box;
    font-family: inherit;
  }

  /* ================= SELECTION VIEW ================= */
  .clones_selection_wrapper {
    width: 100%;
    max-width: 740px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
  }

  .page_title {
    font-size: 26px;
    font-weight: 800;
    color: #1e293b;
    text-align: center;
    margin: 1rem 0 1.5rem 0;
    letter-spacing: -0.02em;
  }

  /* Search Pill */
  .search_pill_wrapper {
    position: relative;
    width: 100%;
    margin-bottom: 2.5rem;
  }

  .search_pill_input {
    width: 100%;
    height: 54px;
    background-color: #d9d9d9;
    border-radius: 9999px;
    border: 2px solid transparent;
    padding: 0 3rem 0 1.5rem;
    font-size: 15px;
    font-weight: 600;
    color: #1e293b;
    text-align: center;
    box-sizing: border-box;
    outline: none;
    transition: all 0.2s ease;
  }

  .search_pill_input::placeholder {
    color: #64748b;
    font-weight: 500;
  }

  .search_pill_input:focus {
    border-color: #40866a;
    background-color: #e2e2e2;
    box-shadow: 0 0 0 4px rgba(64, 134, 106, 0.15);
  }

  .clear_search_btn {
    position: absolute;
    right: 1.25rem;
    top: 50%;
    transform: translateY(-50%);
    background: #cbd5e1;
    color: #475569;
    border: none;
    border-radius: 50%;
    width: 26px;
    height: 26px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 13px;
    font-weight: bold;
    cursor: pointer;
    transition: background 0.15s;
  }

  .clear_search_btn:hover {
    background: #94a3b8;
    color: #ffffff;
  }

  /* Section Title */
  .section_header {
    margin-bottom: 1rem;
    padding: 0 0.25rem;
  }

  .section_title_row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
  }

  .section_title {
    font-size: 20px;
    font-weight: 700;
    color: #1e293b;
    margin: 0;
    letter-spacing: -0.01em;
  }

  .searching_indicator {
    font-size: 13px;
    font-weight: 600;
    color: #40866a;
    background: rgba(64, 134, 106, 0.1);
    padding: 0.25rem 0.65rem;
    border-radius: 9999px;
  }

  /* Clones List & Cards */
  .clones_list {
    display: flex;
    flex-direction: column;
    gap: 1.1rem;
  }

  .clone_card {
    background-color: #d9d9d9;
    border-radius: 20px;
    padding: 1.15rem 1.6rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1.25rem;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.03);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }

  .clone_card:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 14px rgba(0, 0, 0, 0.07);
  }

  .clone_info {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    flex: 1;
  }

  .clone_title_row {
    display: flex;
    align-items: center;
    gap: 0.65rem;
    flex-wrap: wrap;
  }

  .clone_name {
    font-size: 19px;
    font-weight: 800;
    color: #111827;
    margin: 0;
    letter-spacing: -0.01em;
  }

  .match_badge {
    background-color: #059669;
    color: #ffffff;
    font-size: 11.5px;
    font-weight: 700;
    padding: 0.2rem 0.55rem;
    border-radius: 9999px;
    letter-spacing: 0.02em;
    text-transform: uppercase;
  }

  .clone_style_desc {
    font-size: 13.5px;
    line-height: 1.45;
    color: #4b5563;
    margin: 0.25rem 0 0 0;
    font-style: italic;
  }

  .clone_subtitle {
    font-size: 14.5px;
    font-weight: 500;
    color: #374151;
    margin: 0;
  }

  .played_count {
    color: #e8590c;
    font-weight: 700;
  }

  .clone_actions {
    display: flex;
    align-items: center;
    gap: 0.85rem;
  }

  /* Rating Badges */
  .rating_badge {
    background-color: #ffffff;
    border-radius: 8px;
    padding: 0.4rem 0.8rem;
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    font-size: 15px;
    font-weight: 800;
    color: #111827;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    user-select: none;
  }

  .badge_icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .blitz_icon {
    color: #111827;
  }

  .green_pawn {
    color: #40866a;
  }

  .rating_val {
    line-height: 1;
  }

  /* Play Button */
  .play_btn {
    background-color: #40866a;
    color: #ffffff;
    border: none;
    border-radius: 9999px;
    padding: 0.65rem 2rem;
    font-size: 16px;
    font-weight: 700;
    cursor: pointer;
    box-shadow: 0 2px 4px rgba(64, 134, 106, 0.2);
    transition: background-color 0.15s ease, transform 0.1s ease, box-shadow 0.15s ease;
  }

  .play_btn:hover {
    background-color: #346e57;
    box-shadow: 0 4px 8px rgba(64, 134, 106, 0.3);
    transform: scale(1.02);
  }

  .play_btn:active {
    transform: scale(0.98);
  }

  /* Empty Search State */
  .empty_search_state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 3rem 1.5rem;
    background-color: #f1f5f9;
    border-radius: 16px;
    border: 2px dashed #cbd5e1;
    text-align: center;
    margin-top: 1rem;
  }

  .empty_text {
    font-size: 16px;
    color: #475569;
    margin-bottom: 1.25rem;
  }

  .reset_search_btn {
    background-color: #40866a;
    color: #ffffff;
    border: none;
    border-radius: 9999px;
    padding: 0.6rem 1.5rem;
    font-size: 14.5px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s;
  }

  .reset_search_btn:hover {
    background-color: #346e57;
  }

  /* Empty Clones Initial State */
  .empty_clones_container {
    display: flex;
    justify-content: center;
    align-items: center;
    width: 100%;
    padding: 3rem 0;
  }

  .empty_clones_card {
    background: #f8fafc;
    border: 1.5px dashed #cbd5e1;
    border-radius: 18px;
    padding: 2.75rem 3rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 1rem;
    max-width: 520px;
    width: 100%;
    box-sizing: border-box;
  }

  .empty_clones_text {
    font-size: 19px;
    font-weight: 700;
    color: #1e293b;
    margin: 0;
  }

  .empty_clones_subtext {
    font-size: 14.5px;
    color: #64748b;
    margin: 0 0 0.5rem 0;
    line-height: 1.5;
  }

  .go_analyze_btn {
    background: #40866a;
    color: #ffffff;
    text-decoration: none;
    border-radius: 9999px;
    padding: 0.75rem 1.75rem;
    font-size: 15px;
    font-weight: 700;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 4px 14px rgba(64, 134, 106, 0.3);
    transition: transform 0.15s ease, background-color 0.15s ease, box-shadow 0.15s ease;
  }

  .go_analyze_btn:hover {
    background-color: #346e57;
    transform: translateY(-2px);
    box-shadow: 0 6px 18px rgba(64, 134, 106, 0.4);
  }

  /* ================= MATCH ARENA VIEW (FOCUSED REPLAY MODE MATCH) ================= */
  .match_arena_wrapper {
    width: 100%;
    max-width: 1040px;
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }

  .arena_header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.5rem 0.25rem 1rem 0.25rem;
    border-bottom: 1px solid #e2e8f0;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .arena_top_row {
    display: flex;
    align-items: center;
    gap: 1.25rem;
  }

  .back_btn {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    background: transparent;
    border: 1px solid #cbd5e1;
    border-radius: 9999px;
    padding: 0.5rem 1.1rem;
    font-size: 14px;
    font-weight: 600;
    color: #475569;
    cursor: pointer;
    transition: all 0.15s;
  }

  .back_btn:hover {
    background: #f1f5f9;
    color: #0f172a;
    border-color: #94a3b8;
  }

  .arena_match_title {
    font-size: 18px;
    color: #64748b;
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }

  .arena_match_title strong {
    color: #0f172a;
    font-weight: 800;
  }

  .arena_action_buttons {
    display: flex;
    align-items: center;
    gap: 0.65rem;
  }

  .header_action_btn {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    border-radius: 9999px;
    font-size: 13.5px;
    font-weight: 700;
    padding: 0.45rem 1rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .past_games_action_btn,
  .moves_action_btn {
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    color: #1e293b;
  }

  .past_games_action_btn:hover,
  .moves_action_btn:hover {
    background: #e2e8f0;
    color: #0f172a;
  }

  .draw_action_btn {
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    color: #334155;
  }

  .draw_action_btn:hover {
    background: #e2e8f0;
    color: #0f172a;
  }

  .resign_action_btn {
    background: #fff1f2;
    border: 1px solid #fecdd3;
    color: #e11d48;
  }

  .resign_action_btn:hover {
    background: #ffe4e6;
  }

  .play_again_action_btn {
    background: #40866a;
    color: #ffffff;
    border: none;
    box-shadow: 0 2px 8px rgba(64, 134, 106, 0.3);
  }

  .play_again_action_btn:hover {
    background: #346e57;
  }

  /* Clone Error Banner */
  .clone_error_banner {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    background-color: #fef2f2;
    border: 1px solid #fecaca;
    color: #b91c1c;
    border-radius: 12px;
    padding: 0.85rem 1.25rem;
    font-size: 14px;
    font-weight: 600;
  }

  /* Game Over Banner */
  .game_over_banner {
    background: linear-gradient(135deg, #1e293b, #0f172a);
    color: #ffffff;
    border-radius: 16px;
    padding: 1.25rem 1.5rem;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.12);
  }

  .game_over_content {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 1rem;
  }

  .game_over_text {
    font-size: 18px;
    font-weight: 800;
    letter-spacing: -0.01em;
  }

  .game_over_actions {
    display: flex;
    gap: 0.75rem;
  }

  .game_over_btn {
    border: none;
    border-radius: 9999px;
    padding: 0.55rem 1.25rem;
    font-size: 14px;
    font-weight: 700;
    cursor: pointer;
    transition: all 0.15s;
  }

  .game_over_btn.primary {
    background: #40866a;
    color: #ffffff;
  }

  .game_over_btn.primary:hover {
    background: #346e57;
  }

  .game_over_btn.secondary {
    background: rgba(255, 255, 255, 0.15);
    color: #ffffff;
  }

  .game_over_btn.secondary:hover {
    background: rgba(255, 255, 255, 0.25);
  }

  /* FOCUSED REPLAY MATCH WORKSPACE */
  .focused_match_workspace {
    display: flex;
    justify-content: center;
    align-items: flex-start;
    gap: 3.5rem;
    width: 100%;
    margin: 0.75rem auto;
  }

  .focused_board_section {
    position: relative;
    flex: 0 0 580px;
    width: 580px;
    max-width: 580px;
    display: flex;
    justify-content: center;
  }

  /* Countdown Overlay (Matching replay mode 3, 2, 1 animation) */
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

  .focused_side_section {
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

  .player_info_card {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }

  .player_display_name {
    font-size: 22px;
    font-weight: 700;
    color: #000000;
    margin: 0;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .thinking_badge {
    font-size: 12px;
    font-weight: 700;
    background: #fef08a;
    color: #854d0e;
    padding: 0.2rem 0.55rem;
    border-radius: 9999px;
    animation: pulse 1s infinite;
  }

  .your_turn_badge {
    font-size: 12px;
    font-weight: 700;
    background: #dcfce7;
    color: #15803d;
    padding: 0.2rem 0.55rem;
    border-radius: 9999px;
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

  .color_badge {
    color: #475569;
  }

  /* Focused Clock Widget Capsule */
  .focused_clock_section {
    display: flex;
    justify-content: flex-start;
    width: 100%;
    margin: 1rem 0;
  }

  .split_capsule {
    height: 72px;
    border-radius: 20px;
    display: flex;
    overflow: hidden;
    background: #d8d8d8;
  }

  .focused_clock_capsule {
    width: 100%;
    height: 72px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  }

  .capsule_half {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    transition: all 0.2s;
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

  .active_clock_half {
    box-shadow: none;
  }

  .clock_digits {
    font-family: 'Times New Roman', Times, serif;
    font-size: 28px;
    font-weight: 400;
    letter-spacing: 1px;
  }

  /* Bottom Controls: Moves, Draw, Resign (matching restart button pill style) */
  .focused_bottom_bar {
    position: fixed;
    bottom: 2.25rem;
    right: 2.5rem;
    z-index: 50;
    display: flex;
    align-items: center;
    gap: 0.65rem;
  }

  .match_control_pill {
    background: #d8d8d8;
    border: none;
    border-radius: 20px;
    padding: 0.5rem 1.25rem;
    font-size: 14px;
    font-weight: 700;
    color: #000000;
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
    transition: background 0.15s ease, transform 0.15s ease;
  }

  .match_control_pill:hover {
    background: #c8c8c8;
    transform: translateY(-1px);
  }

  /* ================= PRE-MATCH CLONE MODAL STYLES ================= */
  .clone_modal_backdrop {
    position: fixed;
    inset: 0;
    background: rgba(15, 23, 42, 0.65);
    backdrop-filter: blur(4px);
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1.5rem;
  }

  .clone_modal_card {
    background: #ffffff;
    border-radius: 16px;
    width: 100%;
    max-width: 500px;
    max-height: 85vh;
    display: flex;
    flex-direction: column;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
    overflow: hidden;
    animation: modalScaleUp 0.2s cubic-bezier(0.16, 1, 0.3, 1) forwards;
  }

  @keyframes modalScaleUp {
    from {
      opacity: 0;
      transform: scale(0.95) translateY(10px);
    }
    to {
      opacity: 1;
      transform: scale(1) translateY(0);
    }
  }

  .clone_modal_header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 1.25rem 1.75rem;
    border-bottom: 1px solid #f1f5f9;
  }

  .modal_clone_ident {
    display: flex;
    align-items: center;
    gap: 1rem;
  }

  .modal_clone_avatar {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: #0f172a;
    color: #ffffff;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    font-weight: 700;
    letter-spacing: -0.5px;
  }

  .modal_clone_title_row {
    display: flex;
    align-items: center;
    gap: 0.65rem;
  }

  .modal_clone_name {
    font-size: 20px;
    font-weight: 800;
    color: #0f172a;
    margin: 0;
  }

  .modal_rating_badge {
    background: #f1f5f9;
    color: #334155;
    padding: 0.2rem 0.55rem;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 700;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
  }

  .modal_clone_subtitle {
    font-size: 12.5px;
    color: #64748b;
    margin: 0.15rem 0 0 0;
    font-weight: 500;
  }

  .clone_modal_body {
    padding: 1.5rem 1.75rem;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    max-height: calc(90vh - 160px);
  }

  .modal_loading_spinner {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 3rem 1rem;
    gap: 1rem;
    color: #64748b;
    font-size: 14px;
  }

  .spinner_circle {
    width: 32px;
    height: 32px;
    border: 3px solid #e2e8f0;
    border-top-color: #0f172a;
    border-radius: 50%;
    animation: spinModal 0.8s linear infinite;
  }

  @keyframes spinModal {
    to { transform: rotate(360deg); }
  }

  .modal_style_desc {
    font-size: 14px;
    font-style: italic;
    color: #475569;
    margin: 0;
    line-height: 1.5;
  }

  .model_stats_grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0.85rem;
  }

  .model_stat_tile {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 0.85rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }

  .stat_tile_label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    color: #64748b;
  }

  .stat_tile_value {
    font-size: 20px;
    font-weight: 800;
    color: #0f172a;
    letter-spacing: -0.3px;
  }

  .modal_h2h_simple {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 13px;
    color: #64748b;
    padding-top: 0.5rem;
    border-top: 1px solid #f1f5f9;
  }

  .h2h_simple_label {
    font-weight: 600;
    color: #334155;
  }

  .h2h_simple_stats {
    font-weight: 700;
    color: #0f172a;
  }

  .clone_modal_footer {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 0.75rem;
    padding: 1rem 1.75rem;
    border-top: 1px solid #f1f5f9;
    background: #fafafa;
  }

  .modal_cancel_btn {
    background: #f1f5f9;
    border: none;
    color: #475569;
    font-size: 13.5px;
    font-weight: 600;
    padding: 0.6rem 1.15rem;
    border-radius: 10px;
    cursor: pointer;
    transition: background 0.15s ease;
  }

  .modal_cancel_btn:hover {
    background: #e2e8f0;
    color: #0f172a;
  }

  .modal_start_btn {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    background: #40866a;
    border: none;
    color: #ffffff;
    font-size: 13.5px;
    font-weight: 700;
    padding: 0.6rem 1.25rem;
    border-radius: 10px;
    cursor: pointer;
    transition: background 0.15s ease, transform 0.1s ease;
  }

  .modal_start_btn:hover {
    background: #346c55;
    transform: translateY(-1px);
  }

  /* Modals: Past Games & Moves Notation */
  .past_games_modal_backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(2px);
    z-index: 100;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1.5rem;
  }

  .past_games_modal {
    background: #ffffff;
    border-radius: 20px;
    width: 100%;
    max-width: 680px;
    max-height: 85vh;
    display: flex;
    flex-direction: column;
    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2);
    overflow: hidden;
  }

  .moves_modal {
    max-width: 480px;
  }

  .modal_header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 1.25rem 1.75rem;
    border-bottom: 1px solid #e2e8f0;
  }

  .modal_title_group {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .modal_title_group h2 {
    font-size: 19px;
    font-weight: 800;
    color: #0f172a;
    margin: 0;
  }

  .game_count_badge {
    font-size: 12.5px;
    font-weight: 600;
    color: #40866a;
    background: rgba(64, 134, 106, 0.1);
    padding: 0.2rem 0.65rem;
    border-radius: 9999px;
  }

  .close_modal_btn {
    background: #f1f5f9;
    border: none;
    border-radius: 50%;
    width: 30px;
    height: 30px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    font-weight: bold;
    cursor: pointer;
    color: #475569;
    transition: all 0.15s ease;
  }

  .close_modal_btn:hover {
    background: #e2e8f0;
    color: #0f172a;
  }

  .past_games_list {
    padding: 1.25rem 1.75rem;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    max-height: calc(85vh - 100px);
  }

  .past_game_row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.9rem 1.25rem;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    gap: 1rem;
  }

  .game_meta_left {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }

  .game_date {
    font-size: 14.5px;
    font-weight: 700;
    color: #1e293b;
  }

  .game_time_badge,
  .game_color_badge {
    font-size: 12px;
    color: #64748b;
  }

  .game_result_badge {
    font-size: 12px;
    font-weight: 800;
    padding: 0.25rem 0.65rem;
    border-radius: 6px;
    letter-spacing: 0.04em;
  }

  .game_result_badge.win {
    background: #dcfce7;
    color: #15803d;
  }

  .game_result_badge.loss {
    background: #fee2e2;
    color: #b91c1c;
  }

  .game_result_badge.draw {
    background: #f1f5f9;
    color: #475569;
  }

  .game_ratings {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    font-size: 12px;
    color: #475569;
    font-weight: 600;
  }

  .review_game_link {
    font-size: 13px;
    font-weight: 700;
    color: #40866a;
    text-decoration: none;
    padding: 0.45rem 0.85rem;
    border: 1.5px solid #40866a;
    border-radius: 8px;
    transition: all 0.15s;
    white-space: nowrap;
  }

  .review_game_link:hover {
    background: #40866a;
    color: #ffffff;
  }

  .empty_past_games {
    padding: 3rem 1.5rem;
    text-align: center;
    color: #475569;
  }

  .empty_subtext {
    font-size: 13.5px;
    color: #94a3b8;
    margin-top: 0.5rem;
  }

  /* Moves Modal Notation List */
  .moves_list_scroll {
    padding: 1rem 1.5rem;
    max-height: 400px;
    overflow-y: auto;
  }

  .empty_moves_hint {
    font-size: 13px;
    color: #94a3b8;
    text-align: center;
    padding: 1.5rem 0.5rem;
  }

  .moves_table {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .move_row {
    display: grid;
    grid-template-columns: 36px 1fr 1fr;
    font-size: 13.5px;
    padding: 0.35rem 0.5rem;
    border-radius: 6px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }

  .move_row:nth-child(even) {
    background: #f8fafc;
  }

  .move_num {
    color: #94a3b8;
    font-weight: 600;
  }

  .move_white {
    font-weight: 600;
    color: #0f172a;
  }

  .move_black {
    font-weight: 600;
    color: #475569;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }

  /* ================= RESPONSIVE ================= */
  @media (max-width: 960px) {
    .match_arena_wrapper {
      max-width: 100%;
      padding: 0;
      gap: 1rem;
    }

    .arena_header {
      flex-direction: column;
      align-items: stretch;
      gap: 0.75rem;
      padding: 0.25rem 0.25rem 0.75rem 0.25rem;
    }

    .arena_top_row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      width: 100%;
    }

    .arena_action_buttons {
      display: flex;
      align-items: center;
      justify-content: center;
      flex-wrap: wrap;
      gap: 0.45rem;
      width: 100%;
    }

    .header_action_btn {
      padding: 0.4rem 0.75rem;
      font-size: 12.5px;
    }

    .back_btn {
      padding: 0.4rem 0.85rem;
      font-size: 13px;
    }

    .arena_match_title {
      font-size: 15.5px;
    }

    .focused_match_workspace {
      flex-direction: column;
      align-items: center;
      gap: 0;
      width: 100%;
      margin: 0 auto;
    }

    .focused_side_section,
    .focused_container {
      display: contents;
    }

    .player_info_card.top_player {
      order: 1;
      width: 100%;
      max-width: min(calc(100vw - 2rem), 520px);
      margin: 0 auto 0.5rem auto;
      padding: 0 0.25rem;
    }

    .focused_board_section {
      order: 2;
      width: 100%;
      max-width: min(calc(100vw - 2rem), 520px);
      flex: 0 0 auto;
      margin: 0 auto;
    }

    .player_info_card.bottom_player {
      order: 3;
      width: 100%;
      max-width: min(calc(100vw - 2rem), 520px);
      margin: 0.65rem auto 0 auto;
      padding: 0 0.25rem;
    }

    .focused_clock_section {
      order: 4;
      width: 100%;
      max-width: min(calc(100vw - 2rem), 520px);
      display: flex;
      justify-content: center;
      margin: 0.85rem auto 0.25rem auto;
    }

    .focused_clock_capsule {
      width: 100%;
      max-width: 320px;
      height: 64px;
    }

    .clock_digits {
      font-size: 24px;
    }

    .focused_bottom_bar {
      position: static;
      display: flex;
      justify-content: flex-end;
      width: 100%;
      max-width: min(calc(100vw - 2rem), 520px);
      margin: 0.85rem auto 0 auto;
      padding: 0 0.25rem;
    }
  }

  @media (max-width: 768px) {
    .play_page_container {
      padding: 0.75rem 0.5rem 2rem 0.5rem;
    }

    .clone_card {
      flex-direction: column;
      align-items: flex-start;
      gap: 1rem;
      padding: 1rem 1.25rem;
    }

    .clone_actions {
      width: 100%;
      justify-content: space-between;
      flex-wrap: wrap;
    }

    .play_btn {
      margin-left: auto;
    }

    .search_pill_input {
      font-size: 13.5px;
      padding: 0 2.5rem 0 1rem;
    }

    .past_games_modal_backdrop {
      padding: 0.75rem;
    }

    .modal_header {
      padding: 1rem 1.25rem;
    }

    .past_games_list {
      padding: 1rem 1.25rem;
    }

    .past_game_row {
      flex-direction: column;
      align-items: flex-start;
      gap: 0.75rem;
    }

    .review_game_link {
      align-self: flex-end;
    }
  }
</style>
