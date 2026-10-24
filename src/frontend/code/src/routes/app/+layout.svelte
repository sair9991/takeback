<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import '../../app.css';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

  function handleLogout() {
    console.log('Logging out...');
    // Client-side redirect back to the landing/login page
    goto('/');
  }
</script>

<nav class="navigation_bar">
  <a class={page.url.pathname === "/app" ? 'nav_active' : ''} href="/app">Home</a>
  <a class={page.url.pathname.startsWith('/app/analyze') ? 'nav_active' : ''} href="/app/analyze">Analyze</a>
  <a class={page.url.pathname.startsWith('/app/play') ? 'nav_active' : ''} href="/app/play">Play</a>
  <button class="logout_button" onclick={handleLogout}>
    Logout
  </button>
</nav>

{@render children()}
