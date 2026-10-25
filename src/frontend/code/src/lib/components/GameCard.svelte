<script lang="ts">
  import { getInitials, type Game } from '../functions/analyzedGames';

  let { game, onclick }: { game: Game; onclick?: () => void } = $props();

  const initials = $derived(game.initials || getInitials(game.opponent));
  const platformIcon = $derived(
    game.platform.toLowerCase().includes('lichess') ? '/lichess_icon.svg' : '/chess_icon.svg'
  );
</script>

<div
  class="game_card"
  role="button"
  tabindex="0"
  {onclick}
  onkeydown={(e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onclick?.();
    }
  }}
>
  <div class="card_preview">
    {#if game.thumbnailUrl}
      <img src={game.thumbnailUrl} alt="Game preview against {game.opponent}" class="preview_img" />
    {/if}
  </div>

  <div class="card_details">
    <div class="card_info_row">
      <div class="avatar_badge">
        {initials}
      </div>
      <div class="opponent_info">
        <span class="opponent_name">{game.opponent}</span>
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
    transition: transform 0.15s ease, box-shadow 0.15s ease;
    user-select: none;
  }

  .game_card:hover {
    transform: translateY(-3px);
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.08);
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
  }

  .preview_img {
    width: 100%;
    height: 100%;
    object-fit: cover;
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
