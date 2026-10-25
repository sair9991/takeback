<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { logout, getMe } from '../../lib/functions/auth';
  import { fetchUserGames } from '../../lib/functions/userGames';
  import '../../app.css';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

  onMount(async () => {
    const user = await getMe();
    if (!user) {
      goto('/');
      return;
    }
    if (user?.chess_com_username) {
      // Automatically pull in their games from Chess.com upon login
      fetchUserGames(user.chess_com_username, true).catch(() => {});
    }
  });

  async function handleLogout() {
    await logout();
    goto('/');
  }
</script>

<nav class="navigation_bar">
  <a class={page.url.pathname.startsWith('/app/analyze') ? 'nav_active' : ''} href="/app/analyze" aria-label="Analyze" title="Analyze">
    <span class="nav_text">Analyze</span>
    <span class="nav_icon">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="11" cy="11" r="8"></circle>
        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
      </svg>
    </span>
  </a>

  <a class={page.url.pathname.startsWith('/app/explore') || page.url.pathname.startsWith('/app/play') ? 'nav_active' : ''} href="/app/explore" aria-label="Explore" title="Explore">
    <span class="nav_text">Explore</span>
    <span class="nav_icon">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"></circle>
        <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" fill="currentColor"></polygon>
      </svg>
    </span>
  </a>

  <div class="nav_divider"></div>

  <button class="logout_button" onclick={handleLogout} aria-label="Logout" title="Logout">
    <span class="nav_text">Logout</span>
    <span class="nav_icon">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
        <polyline points="16 17 21 12 16 7"></polyline>
        <line x1="21" y1="12" x2="9" y2="12"></line>
      </svg>
    </span>
  </button>
</nav>

<div class="spacer"></div>

<div class="app_content">
  {@render children()}
</div>

