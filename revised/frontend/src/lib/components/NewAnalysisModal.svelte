<script lang="ts">
  import GameCard from './GameCard.svelte';
  import { fetchUserGames, type Game } from '../functions/userGames';
  import { getMe } from '../functions/auth';

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
  let userGames = $state<Game[]>([]);
  let isLoadingGames = $state(false);
  let currentChessHandle = $state('');

  // Function called when user clicks 'Import game' in the modal
  async function handleOpenImportView(forceSync = false) {
    currentView = 'import';
    isLoadingGames = true;
    try {
      const me = await getMe();
      currentChessHandle = me?.chess_com_username || '';
      userGames = await fetchUserGames(currentChessHandle, forceSync);
    } catch (err) {
      console.error('Failed to load user games:', err);
      userGames = [];
    } finally {
      isLoadingGames = false;
    }
  }

  // Reset to main menu whenever the modal is reopened
  $effect(() => {
    if (isOpen) {
      currentView = 'menu';
    }
  });

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

  let manualPgnInput = $state('');
  function handleManualSubmit() {
    if (!manualPgnInput.trim()) return;
    const newGame: Game = {
      id: String(Date.now()),
      opponent: 'Manual Game Analysis',
      date: new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' }),
      platform: 'Custom',
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
          <div class="manual_pgn_box">
            <label for="manual_pgn" class="manual_pgn_label">Paste PGN or moves</label>
            <textarea
              id="manual_pgn"
              class="manual_pgn_textarea"
              placeholder="e.g. 1. e4 e5 2. Nf3 Nc6 3. Bb5 a6..."
              bind:value={manualPgnInput}
              rows="6"
            ></textarea>
          </div>

          <button class="manual_continue_btn" onclick={handleManualSubmit} disabled={!manualPgnInput.trim()}>
            Continue
          </button>
        </div>

      <!-- 4. IMPORT VIEW -->
      {:else if currentView === 'import'}
        <div class="import_view">
          {#if isLoadingGames}
            <div class="import_state_box">
              <div class="spinner_ring"></div>
              <p class="import_state_title">Fetching games from Chess.com...</p>
              <p class="import_state_sub">Checking recent archives for @{currentChessHandle || 'your account'}</p>
            </div>
          {:else if userGames.length === 0}
            <div class="import_state_box">
              <img src="/chess_icon.svg" alt="Chess.com" width="44" height="44" />
              <p class="import_state_title">No Games Found</p>
              <p class="import_state_sub">
                {#if currentChessHandle}
                  No games found for Chess.com account <strong>@{currentChessHandle}</strong>.
                {:else}
                  Please connect your Chess.com account to import games.
                {/if}
              </p>
              <button class="retry_sync_btn" onclick={() => handleOpenImportView(true)}>
                ↻ Sync from Chess.com
              </button>
            </div>
          {:else}
            <div class="import_header_bar">
              <span class="import_count">{userGames.length} games found</span>
              <button class="sync_refresh_btn" onclick={() => handleOpenImportView(true)} title="Sync latest games">
                ↻ Refresh from Chess.com
              </button>
            </div>
            <div class="import_games_grid">
              {#each userGames as game (game.id)}
                <GameCard {game} onclick={() => handleSelectImport(game)} />
              {/each}
            </div>
          {/if}
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

  .import_header_bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 0.5rem 1rem 0.5rem;
  }

  .import_count {
    font-size: 14px;
    font-weight: 600;
    color: #4b5563;
  }

  .sync_refresh_btn {
    background: transparent;
    border: 1px solid #cbd5e1;
    color: #40866a;
    border-radius: 9999px;
    padding: 0.35rem 0.85rem;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .sync_refresh_btn:hover {
    background: #f1f5f9;
    border-color: #40866a;
  }

  .import_state_box {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 3rem 1.5rem;
    text-align: center;
    background: #f8fafc;
    border-radius: 16px;
    border: 2px dashed #e2e8f0;
    margin: 1rem 0;
  }

  .import_state_title {
    font-size: 17px;
    font-weight: 700;
    color: #1e293b;
    margin: 1rem 0 0.25rem 0;
  }

  .import_state_sub {
    font-size: 14px;
    color: #64748b;
    margin: 0 0 1.25rem 0;
    max-width: 320px;
  }

  .retry_sync_btn {
    background: #40866a;
    color: #ffffff;
    border: none;
    border-radius: 9999px;
    padding: 0.6rem 1.4rem;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s;
  }

  .retry_sync_btn:hover {
    background: #346e57;
  }

  .manual_pgn_box {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .manual_pgn_label {
    font-size: 14px;
    font-weight: 700;
    color: #1e293b;
    text-align: left;
  }

  .manual_pgn_textarea {
    width: 100%;
    box-sizing: border-box;
    padding: 0.85rem;
    border-radius: 12px;
    border: 1.5px solid #cbd5e1;
    font-family: monospace;
    font-size: 13.5px;
    resize: vertical;
    outline: none;
  }

  .manual_pgn_textarea:focus {
    border-color: #40866a;
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
