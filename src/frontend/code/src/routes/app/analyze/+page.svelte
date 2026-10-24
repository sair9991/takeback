<script lang="ts">
  import GameCard from '../../../lib/components/GameCard.svelte';
  import NewAnalysisModal from '../../../lib/components/NewAnalysisModal.svelte';
  import { getDummyGames, type Game } from '../../../lib/functions/games';

  let games = $state<Game[]>(getDummyGames());
  let selectedGame = $state<Game | null>(null);
  let isModalOpen = $state(false);

  // Open modal when '+' button is clicked
  function handleOpenModal() {
    isModalOpen = true;
  }

  // Handle game added from modal (video, manual, or import)
  function handleImportGame(game: Game) {
    games = [...games, game];
    selectedGame = game;
    console.log('Added new game for analysis:', game);
  }

  // Dummy function when clicking an existing game card
  function handleSelectGame(game: Game) {
    selectedGame = game;
    console.log('Selected game for analysis:', game);
  }
</script>

<div class="analyze_container">
  <h1 class="page_title">Your Games</h1>

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
