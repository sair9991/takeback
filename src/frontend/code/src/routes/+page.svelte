
<script>
  import Icon from '@iconify/svelte';
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
      <button class="google_login">
        <Icon icon="logos:google-icon" width="15" height="15" />
        &nbsp;
        Continue with Google
      </button>
      <p id="login_divider">
        ------------- or -------------
      </p>
      <input type="text" id="username" placeholder="Enter email" />
      <button class="email_login_button">
        Continue
      </button>
    </div>
  </div>
  <div class="home_right_side">
    <img src="/extended_logo.svg" alt="Company Logo" class="desktop_home_logo" />
  </div>
</div>
