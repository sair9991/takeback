
<script lang="ts">
  import { goto } from '$app/navigation';
  import Icon from '@iconify/svelte';

  let email = $state('');
  let password = $state('');
  let showPassword = $state(false);

  function handleSubmit(event: SubmitEvent) {
    event.preventDefault();
    if (!showPassword) {
      if (email.trim().length > 0) {
        showPassword = true;
      }
    } else {
      console.log('Logging in with:', { email, password });
      goto("/app");
    }
  }
</script>

<div class="home_container">
  <div class="home_left_side">
    <div class="home_login_container">
      <p id="tagline">
        <span id="no">
          No
        </span>
        <span id="regrets">
          Regrets
        </span>
        <span id="period">
          .
        </span>
      </p>
      <button class="google_login" type="button">
        <Icon icon="logos:google-icon" width="15" height="15" />
        &nbsp;
        Continue with Google
      </button>
      <p id="login_divider">
        ------------- or -------------
      </p>
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
        <button type="submit" class="email_login_button">
          {showPassword ? 'Log In' : 'Continue'}
        </button>
      </form>
    </div>
  </div>
  <div class="home_right_side">
    <img src="/extended_logo.svg" alt="Company Logo" class="desktop_home_logo" />
  </div>
</div>
