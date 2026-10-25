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

  let userGames = $state<Game[]>([]);
  let isLoadingGames = $state(false);
  let currentChessHandle = $state('');
  let hasAttemptedInitialLoad = $state(false);

  async function loadGames(forceSync = false) {
    isLoadingGames = true;
    try {
      const me = await getMe();
      const handle = (me?.chess_com_username || me?.user_id || '').trim();
      currentChessHandle = handle;
      if (handle) {
        userGames = await fetchUserGames(handle, forceSync);
      } else {
        userGames = [];
      }
    } catch (err) {
      console.error('Failed to load user games:', err);
      userGames = [];
    } finally {
      isLoadingGames = false;
      hasAttemptedInitialLoad = true;
    }
  }

  // Go straight to Chess.com games on modal open
  $effect(() => {
    if (isOpen) {
      if (!hasAttemptedInitialLoad || userGames.length === 0) {
        loadGames(false);
      }
    }
  });

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
        <img src="/chess_icon.svg" alt="Chess.com" width="26" height="26" class="header_chess_icon" />
        <h2 id="modal-title" class="modal_title">Import Chess.com Games</h2>
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
      {#if isLoadingGames}
        <div class="import_state_box">
          <div class="spinner_ring"></div>
          <p class="import_state_title">Fetching games from Chess.com...</p>
          <p class="import_state_sub">Checking recent archives for @{currentChessHandle.trim() || 'your account'}</p>
        </div>
      {:else if userGames.length === 0}
        <div class="import_state_box">
          <img src="/chess_icon.svg" alt="Chess.com" width="48" height="48" />
          <p class="import_state_title">No 10-Minute Games Found</p>
          <p class="import_state_sub">
            {#if currentChessHandle.trim()}
              No 10-minute games found on Chess.com for account <strong>@{currentChessHandle.trim()}</strong>.
            {:else}
              No Chess.com account linked to your profile yet.
            {/if}
          </p>
          <button class="retry_sync_btn" onclick={() => loadGames(true)}>
            ↻ Sync from Chess.com
          </button>
        </div>
      {:else}
        <div class="import_header_bar">
          <span class="import_count">{userGames.length} 10-minute games found</span>
          <button class="sync_refresh_btn" onclick={() => loadGames(true)} title="Sync latest games" disabled={isLoadingGames}>
            {#if isLoadingGames}
              <span class="btn_spinner"></span>
              <span>Syncing...</span>
            {:else}
              <span>↻ Sync from Chess.com</span>
            {/if}
          </button>
        </div>
        <div class="import_games_grid">
          {#each userGames as game (game.id)}
            <GameCard {game} onclick={() => handleSelectImport(game)} />
          {/each}
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
    max-width: 900px;
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
    margin-bottom: 1.25rem;
  }

  .title_group {
    display: flex;
    align-items: center;
    gap: 0.65rem;
  }

  .header_chess_icon {
    display: block;
  }

  .modal_title {
    font-size: 22px;
    font-weight: 700;
    color: #0f172a;
    margin: 0;
  }

  .close_button {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: #f1f5f9;
    border: none;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    color: #475569;
    transition: all 0.15s ease;
  }

  .close_button:hover {
    background: #e2e8f0;
    color: #0f172a;
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
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    transition: all 0.15s ease;
  }

  .sync_refresh_btn:hover:not(:disabled) {
    background: #f1f5f9;
    border-color: #40866a;
  }

  .sync_refresh_btn:disabled {
    opacity: 0.65;
    cursor: not-allowed;
  }

  .btn_spinner {
    width: 12px;
    height: 12px;
    border: 2px solid #40866a;
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  .modal_body {
    padding: 0.25rem 0;
  }

  .import_header_bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 0.25rem 1rem 0.25rem;
  }

  .import_count {
    font-size: 14px;
    font-weight: 700;
    color: #334155;
  }

  .import_hint {
    font-size: 12.5px;
    color: #64748b;
  }

  .import_games_grid {
    display: flex;
    flex-wrap: wrap;
    gap: 1.5rem;
    justify-content: center;
    padding: 0.5rem 0.25rem;
  }

  .import_state_box {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 3.5rem 1.5rem;
    text-align: center;
    background: #f8fafc;
    border-radius: 16px;
    border: 2px dashed #e2e8f0;
    margin: 1rem 0;
  }

  .spinner_ring {
    width: 36px;
    height: 36px;
    border: 3px solid #e2e8f0;
    border-top: 3px solid #40866a;
    border-radius: 50%;
    animation: spin 0.9s linear infinite;
  }

  @keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
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
    max-width: 340px;
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

  /* Mobile responsiveness */
  @media screen and (max-width: 768px) {
    .modal_dialog {
      padding: 1.25rem 1rem;
      width: 95%;
    }

    .modal_title {
      font-size: 19px;
    }

    .import_header_bar {
      flex-direction: column;
      align-items: flex-start;
      gap: 0.35rem;
    }

    .import_games_grid {
      flex-direction: column;
      align-items: center;
    }
  }
</style>
