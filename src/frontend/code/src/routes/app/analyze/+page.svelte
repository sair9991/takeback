<script lang="ts">
  import { goto } from '$app/navigation';
  import GameCard from '../../../lib/components/GameCard.svelte';
  import NewAnalysisModal from '../../../lib/components/NewAnalysisModal.svelte';
  import { getAnalyzedGames, type Game } from '../../../lib/functions/analyzedGames';

  let games = $state<Game[]>(getAnalyzedGames());
  let selectedGame = $state<Game | null>(null);
  let isModalOpen = $state(false);

  // Open modal when '+' button is clicked
  function handleOpenModal() {
    isModalOpen = true;
  }

  // Handle game added from modal (redirects to the game analysis page)
  function handleImportGame(game: Game) {
    games = [...games, game];
    selectedGame = game;
    console.log('Added new game for analysis:', game);
    goto(`/app/analyze/${game.id}`);
  }

  // When clicking an existing game card, navigate to its analysis page
  function handleSelectGame(game: Game) {
    selectedGame = game;
    console.log('Selected game for analysis:', game);
    goto(`/app/analyze/${game.id}`);
  }
</script>

<div class="analyze_container">
  <h1 class="page_title">Your Games</h1>

  {#if games.length === 0}
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

  .page_title {
    font-size: 28px;
    font-weight: 700;
    color: #000000;
    margin: 0 0 2rem 0;
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
