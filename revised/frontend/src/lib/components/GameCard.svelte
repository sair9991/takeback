<script lang="ts">
  import { getInitials, type Game } from '../functions/analyzedGames';

  let { game, onclick }: { game: Game; onclick?: () => void } = $props();

  const initials = $derived(game.initials || getInitials(game.opponent));
  const platformIcon = $derived(
    game.platform.toLowerCase().includes('lichess') ? '/lichess_icon.svg' : '/chess_icon.svg'
  );

  const previewUrl = $derived.by(() => {
    if (game.thumbnailUrl) {
      return game.thumbnailUrl.startsWith('http')
        ? game.thumbnailUrl
        : `http://localhost:8000${game.thumbnailUrl}`;
    }
    return `http://localhost:8000/api/games/${game.id}/thumbnail.svg`;
  });

  function handleClick() {
    if (game.isTraining) return;
    onclick?.();
  }
</script>

<div
  class="game_card {game.isTraining ? 'is_training' : ''}"
  role="button"
  tabindex={game.isTraining ? -1 : 0}
  onclick={handleClick}
  onkeydown={(e) => {
    if (!game.isTraining && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      handleClick();
    }
  }}
>
  <div class="card_preview">
    {#if game.isTraining}
      <div class="training_overlay">
        <div class="spinner_ring"></div>
        <span class="training_label">Training Model</span>
        <span class="training_status_text">{game.trainingStatus || 'Queued...'}</span>
      </div>
    {:else}
      <img
        src={previewUrl}
        alt="Game preview against {game.opponent}"
        class="preview_img"
        loading="lazy"
      />
    {/if}
  </div>

  <div class="card_details">
    <div class="card_info_row">
      <div class="avatar_badge">
        {initials}
      </div>
      <div class="opponent_info">
        <div class="opponent_header">
          <span class="opponent_name">{game.opponent}</span>
          {#if typeof game.similarity_score === 'number' && game.similarity_score > 0}
            <span class="match_badge">{Math.round(game.similarity_score * 100)}% match</span>
          {/if}
        </div>
        <span class="game_date">{game.date}</span>
      </div>
    </div>

    <div class="platform_badge">
      <img src={platformIcon} alt="{game.platform} icon" class="platform_icon" />
      <span class="platform_text">{game.platform}</span>
    </div>
  </div>
</div>

<style>
  .game_card {
    width: 250px;
    border-radius: 18px;
    border: 1.5px solid #222222;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    background: #ffffff;
    cursor: pointer;
    flex-shrink: 0;
    transition: transform 0.15s ease, box-shadow 0.15s ease, opacity 0.2s ease;
    user-select: none;
  }

  .game_card:hover:not(.is_training) {
    transform: translateY(-3px);
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.08);
  }

  .game_card.is_training {
    opacity: 0.78;
    filter: grayscale(0.2);
    cursor: not-allowed;
    background: #f5f5f5;
  }

  .game_card:focus-visible {
    outline: 2px solid var(--accent-1, #e8590c);
    outline-offset: 2px;
  }

  .card_preview {
    width: 100%;
    height: 210px;
    flex-shrink: 0;
    background: #ffffff;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    position: relative;
  }

  .preview_img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .training_overlay {
    width: 100%;
    height: 100%;
    background: #eaeaea;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 1.25rem 1rem;
    box-sizing: border-box;
    text-align: center;
    gap: 0.65rem;
  }

  .spinner_ring {
    width: 32px;
    height: 32px;
    border: 3px solid #cfcfcf;
    border-top: 3px solid var(--accent-1, #e8590c);
    border-radius: 50%;
    animation: spin 0.9s linear infinite;
  }

  @keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
  }

  .training_label {
    font-size: 13px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #000000;
  }

  .training_status_text {
    font-size: 12px;
    font-weight: 600;
    color: #4b5563;
    line-height: 1.35;
    animation: pulse 1.6s ease-in-out infinite alternate;
  }

  @keyframes pulse {
    0% { opacity: 0.7; }
    100% { opacity: 1; }
  }

  .card_details {
    background: #d8d8d8;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.85rem;
    border-top: 1px solid #222222;
  }

  .card_info_row {
    display: flex;
    align-items: center;
    gap: 0.85rem;
  }

  .avatar_badge {
    width: 46px;
    height: 46px;
    border-radius: 10px;
    background: #808080;
    color: #ffffff;
    font-weight: 700;
    font-size: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .opponent_info {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    flex: 1;
  }

  .opponent_header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.4rem;
  }

  .match_badge {
    background-color: #059669;
    color: #ffffff;
    font-size: 10.5px;
    font-weight: 700;
    padding: 0.15rem 0.45rem;
    border-radius: 9999px;
    letter-spacing: 0.02em;
    flex-shrink: 0;
  }

  .opponent_name {
    font-size: 15px;
    font-weight: 700;
    color: #000000;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .game_date {
    font-size: 13px;
    font-weight: 600;
    color: #1a1a1a;
    margin-top: 3px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .platform_badge {
    background: #ffffff;
    border-radius: 20px;
    padding: 0.35rem 0.85rem;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    width: fit-content;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  }

  .platform_icon {
    width: 18px;
    height: 18px;
    object-fit: contain;
    display: block;
  }

  .platform_text {
    font-size: 13px;
    font-weight: 700;
    color: #000000;
  }

  @media screen and (max-width: 768px) {
    .game_card {
      width: 100%;
      height: auto;
      box-sizing: border-box;
    }

    .card_preview {
      width: 100%;
      height: 240px;
      min-height: 220px;
      flex-shrink: 0;
    }
  }
</style>
