<script lang="ts">
  import GameCard from './GameCard.svelte';
  import { fetchUserGames, getUserGames, type Game } from '../functions/userGames';

  let {
    isOpen,
    onclose,
    onimport
  }: {
    isOpen: boolean;
    onclose: () => void;
    onimport: (game: Game) => void;
  } = $props();

  type ViewType = 'menu' | 'video' | 'manual' | 'import';
  let currentView = $state<ViewType>('menu');
  let userGames = $state<Game[]>(getUserGames());

  // Function called when user clicks 'Import game' in the modal
  async function handleOpenImportView() {
    currentView = 'import';
    userGames = await fetchUserGames();
  }

  // Reset to main menu whenever the modal is reopened
  $effect(() => {
    if (isOpen) {
      currentView = 'menu';
    }
  });

  // Dummy data for manual moves table (matching add_new_analysis_manual.png)
  const dummyMoves = [
    { youTime: '10:00', youMove: 'Be4', themTime: '10:00', themMove: 'Be4' },
    { youTime: '9:30', youMove: 'Be4', themTime: '9:30', themMove: 'Be4' }
  ];

  function handleVideoUpload() {
    const newGame: Game = {
      id: String(Date.now()),
      opponent: 'Video Game Analysis',
      date: new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' }),
      platform: 'Chess.com',
      initials: 'VG'
    };
    onimport(newGame);
    onclose();
  }

  function handleManualSubmit() {
    const newGame: Game = {
      id: String(Date.now()),
      opponent: 'Manual Game Analysis',
      date: new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' }),
      platform: 'Chess.com',
      initials: 'MG'
    };
    onimport(newGame);
    onclose();
  }

  function handleSelectImport(game: Game) {
    onimport(game);
    onclose();
  }
</script>

{#if isOpen}
  <!-- Backdrop -->
  <div class="modal_backdrop" onclick={onclose} role="presentation"></div>

  <!-- Modal Dialog -->
  <div class="modal_dialog" role="dialog" aria-modal="true" aria-labelledby="modal-title">
    <!-- Header -->
    <div class="modal_header">
      <div class="title_group">
        {#if currentView !== 'menu'}
          <button class="back_button" onclick={() => (currentView = 'menu')} aria-label="Back to menu">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <line x1="19" y1="12" x2="5" y2="12"></line>
              <polyline points="12 19 5 12 12 5"></polyline>
            </svg>
          </button>
        {/if}
        <h2 id="modal-title" class="modal_title">
          {#if currentView === 'menu'}
            Analyze a new game
          {:else if currentView === 'video'}
            Video Analysis
          {:else if currentView === 'manual'}
            Enter Moves Manually
          {:else if currentView === 'import'}
            Import Game
          {/if}
        </h2>
      </div>

      <button class="close_button" onclick={onclose} aria-label="Close modal">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
      </button>
    </div>

    <!-- Body Views -->
    <div class="modal_body">
      <!-- 1. MAIN MENU: 3 Option Cards -->
      {#if currentView === 'menu'}
        <div class="menu_grid">
          <button class="option_card" disabled aria-disabled="true" title="Coming soon">
            <div class="option_preview">
              <span>[Gif showing image upload]</span>
            </div>
            <div class="option_footer">
              Submit a video
            </div>
          </button>

          <button class="option_card" disabled aria-disabled="true" title="Coming soon">
            <div class="option_preview">
              <span>[Gif showing manual table input]</span>
            </div>
            <div class="option_footer">
              Enter moves
            </div>
          </button>

          <button class="option_card" onclick={handleOpenImportView}>
            <div class="option_preview">
              <span>[Gif showing Chess.com or LiChess import]</span>
            </div>
            <div class="option_footer">
              Import game
            </div>
          </button>
        </div>

      <!-- 2. VIDEO VIEW -->
      {:else if currentView === 'video'}
        <div class="video_view">
          <button class="video_upload_box" onclick={handleVideoUpload}>
            <svg class="upload_arrow_icon" viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            <span class="upload_text">Upload a chess game video</span>
          </button>
        </div>

      <!-- 3. MANUAL MOVES VIEW -->
      {:else if currentView === 'manual'}
        <div class="manual_view">
          <div class="table_card">
            <!-- Left: You -->
            <div class="table_column">
              <div class="player_title">You</div>
              <div class="col_subheaders">
                <span class="label_time">Time</span>
                <span class="label_move">Move</span>
              </div>
              <div class="rows_list">
                {#each dummyMoves as move}
                  <div class="table_row">
                    <span class="time_val">{move.youTime}</span>
                    <span class="move_chip white_chip">{move.youMove}</span>
                  </div>
                {/each}
              </div>
            </div>

            <!-- Vertical Divider -->
            <div class="column_divider"></div>

            <!-- Right: Them -->
            <div class="table_column">
              <div class="player_title">Them</div>
              <div class="col_subheaders">
                <span class="label_time">Time</span>
                <span class="label_move">Move</span>
              </div>
              <div class="rows_list">
                {#each dummyMoves as move}
                  <div class="table_row">
                    <span class="time_val">{move.themTime}</span>
                    <span class="move_chip black_chip">{move.themMove}</span>
                  </div>
                {/each}
              </div>
            </div>
          </div>

          <button class="manual_continue_btn" onclick={handleManualSubmit}>
            Continue
          </button>
        </div>

      <!-- 4. IMPORT VIEW -->
      {:else if currentView === 'import'}
        <div class="import_view">
          <div class="import_games_grid">
            {#each userGames as game (game.id)}
              <GameCard {game} onclick={() => handleSelectImport(game)} />
            {/each}
          </div>
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .modal_backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    backdrop-filter: blur(2px);
    z-index: 1000;
  }

  .modal_dialog {
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    background: #ffffff;
    border-radius: 20px;
    width: 92%;
    max-width: 880px;
    max-height: 88vh;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 1.75rem 2rem;
    box-shadow: 0 20px 45px rgba(0, 0, 0, 0.25);
    z-index: 1001;
    display: flex;
    flex-direction: column;
    box-sizing: border-box;
  }

  .modal_header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1.5rem;
  }

  .title_group {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .back_button {
    background: transparent;
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0.3rem;
    border-radius: 50%;
    color: #000000;
    transition: background 0.15s;
  }

  .back_button:hover {
    background: #f0f0f0;
  }

  .modal_title {
    font-size: 22px;
    font-weight: 700;
    color: #000000;
    margin: 0;
  }

  .close_button {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: #e2e2e2;
    border: none;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    color: #000000;
    transition: background 0.15s;
    flex-shrink: 0;
  }

  .close_button:hover {
    background: #d4d4d4;
  }

  .modal_body {
    display: flex;
    flex-direction: column;
  }

  /* 1. Main Menu Cards */
  .menu_grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1.25rem;
  }

  .option_card {
    display: flex;
    flex-direction: column;
    background: #ffffff;
    border: none;
    padding: 0;
    border-radius: 6px;
    overflow: hidden;
    cursor: pointer;
    text-align: center;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }

  .option_card:hover:not(:disabled) {
    transform: translateY(-3px);
    box-shadow: 0 6px 16px rgba(0, 0, 0, 0.12);
  }

  .option_card:disabled {
    opacity: 0.45;
    cursor: not-allowed;
    filter: grayscale(0.85);
  }

  .option_preview {
    background: #dcdcdc;
    height: 155px;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
    font-size: 15px;
    font-weight: 700;
    color: #000000;
    line-height: 1.35;
    box-sizing: border-box;
  }

  .option_footer {
    background: #bebebe;
    padding: 0.9rem 0.5rem;
    font-size: 15px;
    font-weight: 700;
    color: #000000;
  }

  /* 2. Video View */
  .video_view {
    display: flex;
    justify-content: center;
    padding: 1rem 0 0.5rem 0;
  }

  .video_upload_box {
    width: 100%;
    height: 250px;
    background: #dcdcdc;
    border: none;
    border-radius: 14px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 1.25rem;
    cursor: pointer;
    transition: background 0.15s ease, transform 0.15s ease;
  }

  .video_upload_box:hover {
    background: #d3d3d3;
    transform: scale(1.01);
  }

  .upload_arrow_icon {
    stroke: #000000;
  }

  .upload_text {
    font-size: 17px;
    font-weight: 700;
    color: #000000;
  }

  /* 3. Manual Moves View */
  .manual_view {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1.5rem;
    padding: 0.5rem 0;
  }

  .table_card {
    background: #dcdcdc;
    border-radius: 20px;
    display: flex;
    width: 100%;
    max-width: 420px;
    padding: 1.25rem 1.5rem;
    box-sizing: border-box;
  }

  .table_column {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .column_divider {
    width: 1px;
    background: #7a7a7a;
    margin: 0 1.25rem;
  }

  .player_title {
    font-size: 17px;
    font-weight: 700;
    color: #000000;
    margin-bottom: 0.5rem;
  }

  .col_subheaders {
    display: flex;
    width: 100%;
    justify-content: space-around;
    font-size: 14px;
    font-weight: 700;
    margin-bottom: 0.75rem;
  }

  .label_time {
    color: var(--accent-2, #40866a);
  }

  .label_move {
    color: var(--accent-1, #e8590c);
  }

  .rows_list {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    width: 100%;
  }

  .table_row {
    display: flex;
    align-items: center;
    justify-content: space-around;
    width: 100%;
  }

  .time_val {
    font-size: 15px;
    font-weight: 700;
    color: #000000;
  }

  .move_chip {
    padding: 0.35rem 1rem;
    border-radius: 20px;
    font-size: 14px;
    font-weight: 700;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 44px;
  }

  .white_chip {
    background: #ffffff;
    color: #000000;
  }

  .black_chip {
    background: #000000;
    color: #ffffff;
  }

  .manual_continue_btn {
    background: var(--accent-1, #e8590c);
    color: #000000;
    border: 1px solid #000000;
    border-radius: 40px;
    padding: 0.8em 4rem;
    font-size: 17px;
    font-weight: 700;
    cursor: pointer;
    transition: transform 0.15s ease, opacity 0.15s ease;
  }

  .manual_continue_btn:hover {
    opacity: 0.92;
    transform: translateY(-2px);
  }

  /* 4. Import View */
  .import_view {
    padding: 0.5rem 0 1rem 0;
    width: 100%;
  }

  .import_games_grid {
    display: flex;
    flex-wrap: wrap;
    gap: 1.5rem;
    justify-content: center;
    padding: 0.5rem 0.25rem;
  }

  /* Mobile responsiveness */
  @media screen and (max-width: 768px) {
    .modal_dialog {
      padding: 1.25rem 1rem;
      width: 95%;
    }

    .modal_title {
      font-size: 19px;
    }

    .menu_grid {
      grid-template-columns: 1fr;
      gap: 1rem;
    }

    .option_preview {
      height: 110px;
    }

    .import_games_grid {
      flex-direction: column;
      align-items: center;
    }
  }
</style>
