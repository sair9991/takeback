<script lang="ts">
  import { goto } from '$app/navigation';
  import Icon from '@iconify/svelte';
  import { login, register, startGoogleAuth, getMe } from '../lib/functions/auth';
  import { onMount } from 'svelte';

  let isSignUp = $state(false);
  let email = $state('');
  let password = $state('');
  let chessUsername = $state('');
  let showPassword = $state(false);
  let loading = $state(false);
  let errorMessage = $state('');

  onMount(async () => {
    // If user already has an active session cookie, redirect to /app
    const user = await getMe();
    if (user) {
      goto('/app');
    }
  });

  async function handleSubmit(event: SubmitEvent) {
    event.preventDefault();
    errorMessage = '';

    if (!showPassword) {
      if (email.trim().length > 0) {
        showPassword = true;
      }
      return;
    }

    loading = true;
    try {
      if (isSignUp) {
        await register(email.trim(), password, chessUsername.trim() || undefined);
      } else {
        await login(email.trim(), password);
      }
      goto('/app');
    } catch (err: any) {
      errorMessage = err?.message || 'Authentication failed. Please check your credentials.';
    } finally {
      loading = false;
    }
  }

  function toggleMode() {
    isSignUp = !isSignUp;
    errorMessage = '';
    showPassword = false;
  }
</script>

<div class="home_container">
  <div class="home_left_side">
    <div class="home_login_container">
      <p id="tagline">
        <span id="no">No</span>
        <span id="regrets">Regrets</span>
        <span id="period">.</span>
      </p>

      <button class="google_login" type="button" onclick={startGoogleAuth}>
        <Icon icon="logos:google-icon" width="15" height="15" />
        &nbsp;
        Continue with Google
      </button>

      <p id="login_divider">
        ------------- or -------------
      </p>

      {#if errorMessage}
        <div class="error_banner">
          {errorMessage}
        </div>
      {/if}

      <form onsubmit={handleSubmit}>
        <input
          type="email"
          id="username"
          placeholder="Enter email"
          bind:value={email}
          required
        />

        {#if showPassword}
          {#if isSignUp}
            <input
              type="text"
              id="chess_username"
              placeholder="Chess.com username (optional)"
              bind:value={chessUsername}
            />
          {/if}
          <input
            type="password"
            id="password"
            placeholder="Enter password"
            bind:value={password}
            required
          />
        {/if}

        <button type="submit" class="email_login_button" disabled={loading}>
          {#if loading}
            Loading...
          {:else}
            {showPassword ? (isSignUp ? 'Create Account' : 'Log In') : 'Continue'}
          {/if}
        </button>
      </form>

      <div class="auth_toggle">
        <button type="button" class="toggle_btn" onclick={toggleMode}>
          {isSignUp ? 'Already have an account? Log In' : "Don't have an account? Sign Up"}
        </button>
      </div>
    </div>
  </div>
  <div class="home_right_side">
    <img src="/extended_logo.svg" alt="Company Logo" class="desktop_home_logo" />
  </div>
</div>

<style>
  .error_banner {
    background: #fee2e2;
    border: 1px solid #f87171;
    color: #b91c1c;
    padding: 0.6rem 0.8rem;
    border-radius: 8px;
    font-size: 13px;
    margin-bottom: 0.75rem;
    text-align: center;
  }

  .auth_toggle {
    margin-top: 1rem;
    text-align: center;
  }

  .toggle_btn {
    background: none;
    border: none;
    color: #475569;
    font-size: 13px;
    cursor: pointer;
    text-decoration: underline;
  }

  .toggle_btn:hover {
    color: #0f172a;
  }
</style>
