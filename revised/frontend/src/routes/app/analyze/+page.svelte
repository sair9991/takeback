<script lang="ts">
  import { onMount } from 'svelte';
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

  let games = $state<Game[]>(getAnalyzedGames());
  let selectedGame = $state<Game | null>(null);
  let isModalOpen = $state(false);
  let searchQuery = $state('');
  let isSearching = $state(false);

  onMount(async () => {
    const loaded = await fetchAnalyzedGames();
    if (loaded && loaded.length > 0) {
      games = loaded;
    }
  });

  // Semantic natural language search with debounce
  $effect(() => {
    const q = searchQuery.trim();
    if (!q) {
      isSearching = false;
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

  async function clearSearch() {
    searchQuery = '';
    const loaded = await fetchAnalyzedGames();
    games = loaded || [];
  }

  // Open modal when '+' button is clicked
  function handleOpenModal() {
    isModalOpen = true;
  }

  // Handle game added from modal (checks model cache, enqueues if needed & streams status)
  async function handleImportGame(game: Game) {
    try {
      const res = await requestGameAnalysis('stuffyness', game.id, game.opponent);

      if (res.cached) {
        games = [...games.filter((g) => g.id !== game.id), game];
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

        games = [...games.filter((g) => g.id !== game.id), trainingGame];

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
      games = [...games.filter((g) => g.id !== game.id), game];
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
  <!-- Search Bar Pill -->
  <div class="search_pill_wrapper">
    <input
      type="text"
      class="search_pill_input"
      placeholder="Search games by opening, style, or narrative (e.g. 'Sicilian blunder', 'endgame squeeze')..."
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

  <div class="section_header">
    <h1 class="page_title">
      {searchQuery ? `Search Results (${games.length})` : 'Your Games'}
    </h1>
    {#if isSearching}
      <span class="searching_indicator">Searching embeddings...</span>
    {/if}
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

  /* Search Pill */
  .search_pill_wrapper {
    position: relative;
    width: 100%;
    max-width: 760px;
    margin: 0.5rem auto 2.25rem auto;
  }

  .search_pill_input {
    width: 100%;
    height: 54px;
    background-color: #d9d9d9;
    border-radius: 9999px;
    border: 2px solid transparent;
    padding: 0 3.25rem 0 1.5rem;
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

  .section_header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1.5rem;
  }

  .page_title {
    font-size: 26px;
    font-weight: 700;
    color: #000000;
    margin: 0;
  }

  .searching_indicator {
    font-size: 13px;
    font-weight: 600;
    color: #40866a;
    background: rgba(64, 134, 106, 0.1);
    padding: 0.3rem 0.75rem;
    border-radius: 9999px;
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
