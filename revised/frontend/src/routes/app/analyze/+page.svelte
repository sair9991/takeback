<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { goto } from '$app/navigation';
  import GameCard from '../../../lib/components/GameCard.svelte';
  import NewAnalysisModal from '../../../lib/components/NewAnalysisModal.svelte';
  import {
    fetchAnalyzedGames,
    getAnalyzedGames,
    searchSemanticAnalyzedGames,
    type Game
  } from '../../../lib/functions/analyzedGames';
  import { requestGameAnalysis } from '../../../lib/functions/userGames';
  import { getMe } from '../../../lib/functions/auth';

  const cachedGames = getAnalyzedGames();
  let initialGames = $state<Game[]>(cachedGames);
  let games = $state<Game[]>(cachedGames);
  let selectedGame = $state<Game | null>(null);
  let isModalOpen = $state(false);
  let searchQuery = $state('');
  let isSearching = $state(false);
  let isSearchExpanded = $state(false);
  let searchInputRef = $state<HTMLInputElement | null>(null);

  onMount(async () => {
    const me = await getMe();
    const handle = me?.chess_com_username || me?.user_id;
    const loaded = await fetchAnalyzedGames(handle);
    if (loaded && loaded.length > 0) {
      initialGames = loaded;
      games = loaded;
    }
  });

  // Semantic natural language search with debounce
  $effect(() => {
    const q = searchQuery.trim();
    if (!q) {
      isSearching = false;
      // When search query is cleared or empty, immediately restore all games
      if (initialGames.length > 0) {
        games = initialGames;
      }
      return;
    }

    isSearching = true;
    const timer = setTimeout(async () => {
      try {
        const results = await searchSemanticAnalyzedGames(q);
        games = results;
      } catch (err) {
        console.error('Semantic game search error:', err);
      } finally {
        isSearching = false;
      }
    }, 250);

    return () => clearTimeout(timer);
  });

  async function expandSearch() {
    isSearchExpanded = true;
    await tick();
    searchInputRef?.focus();
  }

  function collapseSearch() {
    searchQuery = '';
    games = initialGames;
    isSearchExpanded = false;
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      collapseSearch();
    }
  }

  async function clearSearch() {
    searchQuery = '';
    if (initialGames.length > 0) {
      games = initialGames;
    } else {
      const loaded = await fetchAnalyzedGames();
      initialGames = loaded || [];
      games = initialGames;
    }
    searchInputRef?.focus();
  }

  // Open modal when '+' button is clicked
  function handleOpenModal() {
    isModalOpen = true;
  }

  // Handle game added from modal (checks model cache, enqueues if needed & streams status)
  async function handleImportGame(game: Game) {
    try {
      const me = await getMe();
      const handle = me?.chess_com_username || me?.user_id || 'guest';
      const res = await requestGameAnalysis(handle, game.id, game.opponent);

      if (res.cached) {
        const updated = [...initialGames.filter((g) => g.id !== game.id), game];
        initialGames = updated;
        games = updated;
        selectedGame = game;
        goto(`/app/analyze/${game.id}`);
      } else {
        // Opponent model not cached: Show card grayed out with loading indicator & stream progress
        const trainingGame: Game = {
          ...game,
          isTraining: true,
          trainingStatus: res.message || 'Queued for training...',
          jobId: res.job_id,
        };

        const updated = [...initialGames.filter((g) => g.id !== game.id), trainingGame];
        initialGames = updated;
        games = updated;

        if (res.job_id) {
          const streamUrl = `http://localhost:8000/api/analysis/stream/${res.job_id}`;
          const es = new EventSource(streamUrl);

          es.onmessage = (event) => {
            try {
              const data = JSON.parse(event.data);
              const idx = games.findIndex((g) => g.id === game.id);
              if (idx !== -1) {
                if (data.message) {
                  games[idx].trainingStatus = data.message;
                }
                if (data.status === 'completed') {
                  games[idx].isTraining = false;
                  const initIdx = initialGames.findIndex((g) => g.id === game.id);
                  if (initIdx !== -1) initialGames[initIdx].isTraining = false;
                  es.close();
                } else if (data.status === 'failed') {
                  games[idx].trainingStatus = `Failed: ${data.message || 'Error'}`;
                  es.close();
                }
              }
            } catch (err) {
              console.error('Error parsing SSE event:', err);
            }
          };

          es.onerror = () => {
            es.close();
          };
        }
      }
    } catch (err) {
      console.warn('Backend unavailable, importing directly:', err);
      const updated = [...initialGames.filter((g) => g.id !== game.id), game];
      initialGames = updated;
      games = updated;
      goto(`/app/analyze/${game.id}`);
    }
  }

  // When clicking an existing game card, navigate to its analysis page
  function handleSelectGame(game: Game) {
    if (game.isTraining) return;
    selectedGame = game;
    console.log('Selected game for analysis:', game);
    goto(`/app/analyze/${game.id}`);
  }
</script>

<div class="analyze_container">
  <div class="section_header">
    <div class="header_title_wrap">
      <h1 class="page_title">
        {searchQuery ? `Search Results (${games.length})` : 'Your Games'}
      </h1>
    </div>

    <!-- Inline Search Button / Expandable Pill -->
    <div class="header_search_wrap {isSearchExpanded ? 'expanded' : ''}">
      {#if !isSearchExpanded}
        <button
          class="search_circle_btn"
          onclick={expandSearch}
          aria-label="Search games"
          title="Search games"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </button>
      {:else}
        <div class="search_pill_wrapper">
          <div class="search_icon_prefix">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#64748b" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </div>
          <input
            bind:this={searchInputRef}
            type="text"
            class="search_pill_input"
            placeholder="Search games by opening, style, or narrative (e.g. 'Sicilian blunder', 'endgame squeeze')..."
            bind:value={searchQuery}
            onkeydown={handleKeydown}
          />
          <button
            class="close_search_btn"
            onclick={collapseSearch}
            aria-label="Close search"
            title="Close search"
          >
            ✕
          </button>
        </div>
      {/if}
    </div>
  </div>

  {#if games.length === 0 && searchQuery}
    <!-- Empty Search State -->
    <div class="empty_search_state">
      <p class="empty_text">No analyzed games found matching "<strong>{searchQuery}</strong>"</p>
      <button class="reset_search_btn" onclick={clearSearch}>
        Clear Search
      </button>
    </div>
  {:else if games.length === 0}
    <div class="empty_games_container">
      <div class="empty_games_card">
        <p class="empty_games_text">
          You haven't analyzed any games yet. Start now!
        </p>
        <button
          class="start_analyzing_btn"
          onclick={handleOpenModal}
          aria-label="Start analyzing a game"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          <span>Start Analyzing</span>
        </button>
      </div>
    </div>
  {:else}
    <div class="games_container">
      {#each games as game (game.id)}
        <GameCard {game} onclick={() => handleSelectGame(game)} />
      {/each}

      <!-- Add Game Button -->
      <div class="add_btn_wrapper">
        <button
          class="add_game_btn"
          onclick={handleOpenModal}
          aria-label="Add new game"
          title="Add new game"
        >
          <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
      </div>
    </div>
  {/if}

  {#if selectedGame}
    <div class="selected_game_banner">
      <p>
        Ready to analyze game vs. <strong>{selectedGame.opponent}</strong> ({selectedGame.date}) on {selectedGame.platform}.
      </p>
    </div>
  {/if}

  <!-- New Analysis Modal -->
  <NewAnalysisModal
    isOpen={isModalOpen}
    onclose={() => (isModalOpen = false)}
    onimport={handleImportGame}
  />
</div>

<style>
  .analyze_container {
    max-width: 1400px;
    margin: 0 auto;
    padding: 1.5rem 2rem;
  }

  /* Header & Inline Search */
  .section_header {
    display: flex;
    align-items: center;
    gap: 1.25rem;
    margin-bottom: 1.75rem;
    min-height: 46px;
  }

  .header_title_wrap {
    display: flex;
    align-items: center;
    gap: 0.85rem;
    flex-shrink: 0;
  }

  .page_title {
    font-size: 26px;
    font-weight: 700;
    color: #000000;
    margin: 0;
    white-space: nowrap;
  }

  .searching_indicator {
    font-size: 13px;
    font-weight: 600;
    color: #40866a;
    background: rgba(64, 134, 106, 0.1);
    padding: 0.3rem 0.75rem;
    border-radius: 9999px;
  }

  .header_search_wrap {
    display: flex;
    align-items: center;
    transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  }

  .header_search_wrap.expanded {
    flex: 1;
    max-width: 620px;
  }

  .search_circle_btn {
    width: 42px;
    height: 42px;
    border-radius: 50%;
    background-color: #d9d9d9;
    border: none;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #334155;
    cursor: pointer;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
    transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  }

  .search_circle_btn:hover {
    background-color: #cecece;
    color: #0f172a;
    transform: scale(1.08);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
  }

  .search_circle_btn:active {
    transform: scale(0.96);
  }

  .search_pill_wrapper {
    position: relative;
    width: 100%;
    display: flex;
    align-items: center;
    animation: expandInlinePill 0.22s cubic-bezier(0.16, 1, 0.3, 1) forwards;
  }

  @keyframes expandInlinePill {
    from {
      opacity: 0;
      transform: scaleX(0.92);
    }
    to {
      opacity: 1;
      transform: scaleX(1);
    }
  }

  .search_icon_prefix {
    position: absolute;
    left: 1.15rem;
    top: 50%;
    transform: translateY(-50%);
    display: flex;
    align-items: center;
    justify-content: center;
    pointer-events: none;
  }

  .search_pill_input {
    width: 100%;
    height: 44px;
    background-color: #d9d9d9;
    border-radius: 9999px;
    border: 2px solid transparent;
    padding: 0 2.75rem 0 2.75rem;
    font-size: 14.5px;
    font-weight: 600;
    color: #1e293b;
    text-align: left;
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
    box-shadow: 0 0 0 3px rgba(64, 134, 106, 0.15);
  }

  .close_search_btn {
    position: absolute;
    right: 0.85rem;
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
    font-size: 12px;
    font-weight: bold;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .close_search_btn:hover {
    background: #94a3b8;
    color: #ffffff;
    transform: translateY(-50%) scale(1.1);
  }

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

  .empty_games_container {
    display: flex;
    justify-content: center;
    align-items: center;
    width: 100%;
    padding: 2.5rem 0 3.5rem 0;
  }

  .empty_games_card {
    background: #f7f7f7;
    border: 1.5px dashed #cccccc;
    border-radius: 18px;
    padding: 2.75rem 3rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 1.5rem;
    max-width: 540px;
    width: 100%;
    box-sizing: border-box;
    margin: 0 auto;
  }

  .empty_games_text {
    font-size: 18px;
    font-weight: 600;
    color: #2b2b2b;
    margin: 0;
    line-height: 1.5;
    text-align: center;
  }

  .start_analyzing_btn {
    background: var(--accent-2, #40866a);
    color: #ffffff;
    border: none;
    border-radius: 40px;
    padding: 0.75rem 1.75rem;
    font-size: 15px;
    font-weight: 700;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    cursor: pointer;
    box-shadow: 0 4px 14px rgba(64, 134, 106, 0.35);
    transition: transform 0.15s ease, opacity 0.15s ease, box-shadow 0.15s ease;
  }

  .start_analyzing_btn:hover {
    transform: translateY(-2px);
    opacity: 0.93;
    box-shadow: 0 6px 18px rgba(64, 134, 106, 0.45);
  }

  .games_container {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 1.75rem;
    padding-bottom: 1.5rem;
  }

  .add_btn_wrapper {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .add_game_btn {
    width: 58px;
    height: 58px;
    border-radius: 50%;
    background: #d8d8d8;
    border: none;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    color: #000000;
    transition: background 0.15s ease, transform 0.15s ease;
  }

  .add_game_btn:hover {
    background: #c8c8c8;
    transform: scale(1.05);
  }

  .add_game_btn:active {
    transform: scale(0.96);
  }

  .selected_game_banner {
    margin-top: 2rem;
    padding: 1rem 1.25rem;
    background: #f3f4f6;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    color: #374151;
    font-size: 15px;
  }

  .selected_game_banner p {
    margin: 0;
  }

  @media screen and (max-width: 768px) {
    .analyze_container {
      padding: 1rem;
    }

    .page_title {
      font-size: 24px;
      margin-bottom: 1.25rem;
    }

    .empty_games_card {
      padding: 1.5rem 1.25rem;
    }

    .games_container {
      flex-direction: column;
      align-items: stretch;
      gap: 1.25rem;
    }

    .add_btn_wrapper {
      width: 100%;
      display: flex;
      justify-content: center;
      padding: 0.75rem 0;
    }
  }
</style>
