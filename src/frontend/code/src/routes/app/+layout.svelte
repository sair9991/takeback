<script lang="ts">
  import '../../app.css';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
</script>

<nav>
  <a href="/">Home</a>
  <a href="/about">About</a>
  <a href="/dashboard">Dashboard</a>
</nav>
{@render children()}
