<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import Icon from '@iconify/svelte';
  import { login, register, startGoogleAuth, getMe, updateProfile } from '../lib/functions/auth';
  import { onMount } from 'svelte';

  type Screen = 'auth' | 'connect_chess';
  let currentScreen = $state<Screen>('auth');

  let isSignUp = $state(false);
  let email = $state('');
  let password = $state('');
  let chessUsername = $state('');
  let showPassword = $state(false);
  let loading = $state(false);
  let errorMessage = $state('');

  onMount(async () => {
    // If user already has an active session cookie, check if chess.com is linked
    const user = await getMe();
    if (user) {
      if (!user.chess_com_username || page.url.searchParams.get('connect') === 'true') {
        currentScreen = 'connect_chess';
      } else {
        goto('/app');
      }
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
        await register(email.trim(), password);
        // On successful signup, immediately take them to the required Chess.com connection screen
        currentScreen = 'connect_chess';
      } else {
        const user = await login(email.trim(), password);
        if (!user.chess_com_username) {
          currentScreen = 'connect_chess';
        } else {
          goto('/app');
        }
      }
    } catch (err: any) {
      errorMessage = err?.message || 'Authentication failed. Please check your credentials.';
    } finally {
      loading = false;
    }
  }

  async function handleConnectChessCom(event: SubmitEvent) {
    event.preventDefault();
    const handle = chessUsername.trim();
    if (!handle) {
      errorMessage = 'Chess.com username is required to proceed.';
      return;
    }

    loading = true;
    errorMessage = '';
    try {
      await updateProfile({ chess_com_username: handle });
      goto('/app');
    } catch (err: any) {
      errorMessage = err?.message || 'Failed to link Chess.com account. Please try again.';
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

      {#if currentScreen === 'connect_chess'}
        <!-- ================= REQUIRED CHESS.COM CONNECT SCREEN ================= -->
        <div class="connect_chess_card">
          <div class="connect_icon_badge">
            <img src="/chess_icon.svg" alt="Chess.com" width="36" height="36" />
          </div>

          <h2 class="connect_title">Connect Chess.com</h2>
          <p class="connect_desc">
            A Chess.com account is <strong>required</strong> to analyze your games, calibrate your cognitive metrics, and train your clone.
          </p>

          {#if errorMessage}
            <div class="error_banner">
              {errorMessage}
            </div>
          {/if}

          <form onsubmit={handleConnectChessCom}>
            <input
              type="text"
              id="chess_username_required"
              class="connect_input"
              placeholder="Enter Chess.com username (e.g. stuffyness)"
              bind:value={chessUsername}
              required
            />

            <button type="submit" class="email_login_button connect_submit_btn" disabled={loading || !chessUsername.trim()}>
              {#if loading}
                Connecting...
              {:else}
                Connect &amp; Enter App
              {/if}
            </button>
          </form>
        </div>
      {:else}
        <!-- ================= STANDARD AUTH SCREEN (LOGIN / SIGN UP) ================= -->
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
      {/if}
    </div>
  </div>
  <div class="home_right_side">
    <img src="/extended_logo.svg" alt="Company Logo" class="desktop_home_logo" />
  </div>
</div>

<style>
  .connect_chess_card {
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    width: 100%;
    margin-top: 0.5rem;
  }

  .connect_icon_badge {
    width: 60px;
    height: 60px;
    background: #ffffff;
    border-radius: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
    margin-bottom: 1rem;
  }

  .connect_title {
    font-size: 21px;
    font-weight: 800;
    color: #0f172a;
    margin: 0 0 0.5rem 0;
  }

  .connect_desc {
    font-size: 13.5px;
    line-height: 1.5;
    color: #475569;
    margin: 0 0 1.25rem 0;
    max-width: 320px;
  }

  .connect_desc strong {
    color: #0f172a;
  }

  .connect_input {
    width: 100%;
    box-sizing: border-box;
  }

  .connect_submit_btn {
    margin-top: 0.75rem;
  }

  .error_banner {
    background: #fee2e2;
    border: 1px solid #f87171;
    color: #b91c1c;
    padding: 0.6rem 0.8rem;
    border-radius: 8px;
    font-size: 13px;
    margin-bottom: 0.75rem;
    text-align: center;
    width: 100%;
    box-sizing: border-box;
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
