<script lang="ts">
  import '@fontsource/inter';
  import '../app.css';
	import favicon from '#lib/assets/favicon.svg';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
</script>

<div class="logo">
  <img src="/small_logo.svg" alt="Company Logo" class="small_logo" height="50em" />
</div>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

{@render children()}
