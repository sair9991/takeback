<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { logout } from '../../lib/functions/auth';
  import '../../app.css';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

  async function handleLogout() {
    await logout();
    goto('/');
  }
</script>

<nav class="navigation_bar">
  <a class={page.url.pathname === "/app" ? 'nav_active' : ''} href="/app" aria-label="Home" title="Home">
    <span class="nav_text">Home</span>
    <span class="nav_icon">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
        <polyline points="9 22 9 12 15 12 15 22"></polyline>
      </svg>
    </span>
  </a>

  <a class={page.url.pathname.startsWith('/app/analyze') ? 'nav_active' : ''} href="/app/analyze" aria-label="Analyze" title="Analyze">
    <span class="nav_text">Analyze</span>
    <span class="nav_icon">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="11" cy="11" r="8"></circle>
        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
      </svg>
    </span>
  </a>

  <a class={page.url.pathname.startsWith('/app/play') ? 'nav_active' : ''} href="/app/play" aria-label="Play" title="Play">
    <span class="nav_text">Play</span>
    <span class="nav_icon">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
        <polygon points="6 4 20 12 6 20 6 4"></polygon>
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

