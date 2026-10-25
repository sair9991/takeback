<script lang="ts">
  import { onDestroy } from 'svelte';
  import { Chess, type Square } from 'chess.js';
  import Chessboard from '../../../lib/components/Chessboard.svelte';
  import { getClones, fetchClones, requestCloneMove } from '../../../lib/functions/clones';
  import type { Clone } from '../../../lib/types/clone';

  // Search state
  let searchQuery = $state('');
  let clones = $state<Clone[]>(getClones());
  let isSearching = $state(false);

  // Debounced search querying backend vector / style search
  $effect(() => {
    const q = searchQuery;
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

  // Match / Play Arena State
  let selectedClone = $state<Clone | null>(null);
  let chess = $state<Chess | null>(null);
  let gameFen = $state('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1');
  let moveHistory = $state<{ num: number; white: string; black?: string }[]>([]);
  let isCloneThinking = $state(false);
  let cloneError = $state<string | null>(null);
  let gameOverMessage = $state<string | null>(null);

  // Clocks (10 minutes = 600s)
  let playerTime = $state(600);
  let cloneTime = $state(600);
  let timerInterval: ReturnType<typeof setInterval> | null = null;

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
    startTimer();
  }

  function exitMatch() {
    stopTimer();
    selectedClone = null;
    chess = null;
    cloneError = null;
    gameOverMessage = null;
  }

  function handlePlayerMove(move: { from: string; to: string; san: string }) {
    if (!chess || isCloneThinking || gameOverMessage) return;

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

  function resignMatch() {
    if (gameOverMessage || !chess) return;
    stopTimer();
    gameOverMessage = `You resigned. ${selectedClone?.name} wins.`;
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
            onclick={() => (searchQuery = '')}
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
          {#if isSearching}
            <span class="searching_indicator">Searching embeddings...</span>
          {/if}
        </div>
      </div>

      <!-- Clones List -->
      {#if clones.length > 0}
        <div class="clones_list">
          {#each clones as clone (clone.id)}
            <div class="clone_card">
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
                <!-- Badge 1: Blitz / Speed Rating -->
                <div class="rating_badge" title="Blitz / Speed Rating">
                  <svg
                    class="badge_icon blitz_icon"
                    viewBox="0 0 24 24"
                    width="16"
                    height="16"
                    fill="currentColor"
                  >
                    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
                  </svg>
                  <span class="rating_val">{clone.blitzRating}</span>
                </div>

                <!-- Badge 2: Clone Pawn Rating -->
                <div class="rating_badge pawn_badge" title="Clone Rating">
                  <svg
                    class="badge_icon green_pawn"
                    viewBox="0 0 24 24"
                    width="16"
                    height="16"
                    fill="currentColor"
                  >
                    <path
                      d="M12 2a3 3 0 0 0-3 3c0 .87.37 1.66.97 2.21C8.29 8.2 7 10.45 7 13.5c0 1.25.4 2.1 1 2.5v1H7v2h10v-2h-1v-1c.6-.4 1-1.25 1-2.5 0-3.05-1.29-5.3-2.97-6.29.6-.55.97-1.34.97-2.21a3 3 0 0 0-3-3z"
                    />
                  </svg>
                  <span class="rating_val">{clone.cloneRating}</span>
                </div>

                <!-- Play Button -->
                <button
                  class="play_btn"
                  onclick={() => startMatch(clone)}
                  aria-label={`Play against ${clone.name}`}
                >
                  Play
                </button>
              </div>
            </div>
          {/each}
        </div>
      {:else}
        <!-- Empty Search State -->
        <div class="empty_search_state">
          <p class="empty_text">No clones found matching "<strong>{searchQuery}</strong>"</p>
          <button class="reset_search_btn" onclick={() => (searchQuery = '')}>
            Clear Search
          </button>
        </div>
      {/if}
    </div>
  {:else}
    <!-- ================= INTERACTIVE CHESS MATCH ARENA ================= -->
    <div class="match_arena_wrapper">
      <!-- Arena Top Bar -->
      <div class="arena_header">
        <button class="back_btn" onclick={exitMatch}>
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 18 9 12 15 6"></polyline>
          </svg>
          Back to Clones
        </button>

        <div class="arena_match_title">
          <span>Match vs</span>
          <strong>{selectedClone.name}</strong>
        </div>

        <button class="resign_btn" onclick={resignMatch} disabled={!!gameOverMessage}>
          Resign
        </button>
      </div>

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
                Choose Another Clone
              </button>
            </div>
          </div>
        </div>
      {/if}

      <!-- Match Layout (Board + Side Panel) -->
      <div class="match_layout">
        <!-- Chessboard Column -->
        <div class="board_column">
          <!-- Opponent Bar -->
          <div class="player_strip opponent_strip">
            <div class="player_identity">
              <div class="avatar_badge opponent_avatar">
                {selectedClone.initials || selectedClone.name.slice(0, 2).toUpperCase()}
              </div>
              <div class="player_meta">
                <span class="player_display_name">{selectedClone.name}</span>
                <span class="player_subtext">
                  {#if isCloneThinking}
                    <span class="thinking_dot">●</span> Thinking...
                  {:else if chess?.turn() === 'b'}
                    Clone's turn
                  {:else}
                    Waiting for your move
                  {/if}
                </span>
              </div>
            </div>

            <!-- Opponent Clock Capsule -->
            <div class="clock_capsule {chess?.turn() === 'b' && !gameOverMessage ? 'active_clock' : ''}">
              <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor">
                <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"></circle>
                <polyline points="12 6 12 12 16 14" fill="none" stroke="currentColor" stroke-width="2"></polyline>
              </svg>
              <span>{formatTime(cloneTime)}</span>
            </div>
          </div>

          <!-- The Chessboard -->
          <div class="board_stage">
            <Chessboard
              fen={gameFen}
              interactive={!isCloneThinking && !gameOverMessage && chess?.turn() === 'w'}
              orientation="white"
              viewMode="expanded"
              onmove={handlePlayerMove}
            />
          </div>

          <!-- User Player Bar -->
          <div class="player_strip user_strip">
            <div class="player_identity">
              <div class="avatar_badge user_avatar">YOU</div>
              <div class="player_meta">
                <span class="player_display_name">You (White)</span>
                <span class="player_subtext">
                  {#if chess?.turn() === 'w' && !gameOverMessage}
                    <span class="your_turn_dot">●</span> Your turn
                  {:else if !gameOverMessage}
                    Opponent thinking
                  {:else}
                    Match finished
                  {/if}
                </span>
              </div>
            </div>

            <!-- User Clock Capsule -->
            <div class="clock_capsule {chess?.turn() === 'w' && !gameOverMessage ? 'active_clock' : ''}">
              <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor">
                <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"></circle>
                <polyline points="12 6 12 12 16 14" fill="none" stroke="currentColor" stroke-width="2"></polyline>
              </svg>
              <span>{formatTime(playerTime)}</span>
            </div>
          </div>
        </div>

        <!-- Sidebar / Move History Column -->
        <div class="match_sidebar">
          <div class="sidebar_card clone_summary_card">
            <div class="clone_summary_header">
              <h3>{selectedClone.name}</h3>
              <p>{selectedClone.styleDescription || selectedClone.bio || 'AI Clone modelled after playing style and past games.'}</p>
            </div>
            <div class="clone_summary_stats">
              <div class="stat_pill">
                <span class="stat_label">Blitz</span>
                <span class="stat_num">{selectedClone.blitzRating}</span>
              </div>
              <div class="stat_pill">
                <span class="stat_label">Clone</span>
                <span class="stat_num">{selectedClone.cloneRating}</span>
              </div>
              <div class="stat_pill">
                <span class="stat_label">Played</span>
                <span class="stat_num orange_text">{selectedClone.playedCount}</span>
              </div>
            </div>
          </div>

          <!-- Moves Notation Container -->
          <div class="sidebar_card notation_card">
            <div class="notation_header">
              <h4>Move History</h4>
              <span class="moves_count">{moveHistory.length} moves</span>
            </div>
            <div class="moves_list_scroll">
              {#if moveHistory.length === 0}
                <div class="empty_moves_hint">Game has started. Make your first move!</div>
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
      </div>
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

  /* ================= MATCH ARENA VIEW ================= */
  .match_arena_wrapper {
    width: 100%;
    max-width: 960px;
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }

  .arena_header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.5rem 0.25rem;
    border-bottom: 1px solid #e2e8f0;
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
    font-size: 17px;
    color: #64748b;
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }

  .arena_match_title strong {
    color: #0f172a;
    font-weight: 700;
  }

  .resign_btn {
    background: transparent;
    color: #e11d48;
    border: 1px solid #fecdd3;
    border-radius: 9999px;
    padding: 0.5rem 1.25rem;
    font-size: 13.5px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
  }

  .resign_btn:hover:not(:disabled) {
    background: #ffe4e6;
  }

  .resign_btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
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

  /* Match Layout */
  .match_layout {
    display: grid;
    grid-template-columns: minmax(0, 520px) 1fr;
    gap: 1.75rem;
    align-items: start;
    justify-content: center;
  }

  .board_column {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .player_strip {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.65rem 1rem;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
  }

  .player_identity {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .avatar_badge {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 13px;
    font-weight: 800;
  }

  .opponent_avatar {
    background: #e2e8f0;
    color: #1e293b;
  }

  .user_avatar {
    background: #40866a;
    color: #ffffff;
  }

  .player_meta {
    display: flex;
    flex-direction: column;
  }

  .player_display_name {
    font-size: 15px;
    font-weight: 700;
    color: #0f172a;
    line-height: 1.2;
  }

  .player_subtext {
    font-size: 12.5px;
    color: #64748b;
    display: flex;
    align-items: center;
    gap: 0.35rem;
  }

  .thinking_dot {
    color: #eab308;
    animation: pulse 1s infinite;
  }

  .your_turn_dot {
    color: #10b981;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }

  .clock_capsule {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 0.35rem 0.75rem;
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 15px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: #334155;
    transition: all 0.2s;
  }

  .clock_capsule.active_clock {
    border-color: #40866a;
    background-color: #ecfdf5;
    color: #065f46;
    box-shadow: 0 0 0 2px rgba(64, 134, 106, 0.2);
  }

  .board_stage {
    width: 100%;
    aspect-ratio: 1 / 1;
    background: #e2e8f0;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  }

  /* Sidebar */
  .match_sidebar {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .sidebar_card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 16px;
    padding: 1.25rem;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  }

  .clone_summary_header h3 {
    font-size: 17px;
    font-weight: 800;
    color: #0f172a;
    margin: 0 0 0.35rem 0;
  }

  .clone_summary_header p {
    font-size: 13.5px;
    color: #64748b;
    margin: 0 0 1rem 0;
    line-height: 1.4;
  }

  .clone_summary_stats {
    display: flex;
    gap: 0.65rem;
  }

  .stat_pill {
    flex: 1;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 0.5rem 0.6rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.15rem;
  }

  .stat_label {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    color: #64748b;
    letter-spacing: 0.05em;
  }

  .stat_num {
    font-size: 15px;
    font-weight: 800;
    color: #0f172a;
  }

  .stat_num.orange_text {
    color: #e8590c;
  }

  /* Move Notation */
  .notation_header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.85rem;
    border-bottom: 1px solid #f1f5f9;
    padding-bottom: 0.5rem;
  }

  .notation_header h4 {
    font-size: 15px;
    font-weight: 700;
    color: #0f172a;
    margin: 0;
  }

  .moves_count {
    font-size: 12.5px;
    color: #64748b;
    font-weight: 500;
  }

  .moves_list_scroll {
    max-height: 260px;
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

  /* ================= RESPONSIVE ================= */
  @media (max-width: 768px) {
    .match_layout {
      grid-template-columns: 1fr;
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
  }
</style>
