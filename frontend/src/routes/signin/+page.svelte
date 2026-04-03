<script>
  import { goto } from '$app/navigation';
  import { login as apiLogin, register as apiRegister } from '$lib/api';
  import { authStore } from '$lib/stores';

  let tab       = $state('signin');   // signin or register
  let loading   = $state(false);
  let error     = $state('');

  let signinForm = $state({ username: '', password: '' });
  let regForm    = $state({ username: '', password: '', confirm: '', display_name: '', email: '', phone: '', pan: '' });

  async function signin() {
    loading = true; error = '';
    try {
      const data = await apiLogin(signinForm.username, signinForm.password);
      authStore.login(data.access_token, {
        username:     data.username,
        role:         data.role,
        display_name: data.display_name,
      });
      goto(data.role === 'admin' ? '/performance' : '/portfolio');
    } catch (e) {
      error = e.message;
    } finally { loading = false; }
  }

  async function register() {
    loading = true; error = '';
    if (regForm.password !== regForm.confirm) { error = 'Passwords do not match'; loading = false; return; }
    if (regForm.password.length < 8)          { error = 'Password must be at least 8 characters'; loading = false; return; }
    try {
      const data = await apiRegister({
        username:     regForm.username,
        password:     regForm.password,
        display_name: regForm.display_name || regForm.username,
        email:        regForm.email,
        phone:        regForm.phone,
        pan:          regForm.pan,
      });
      authStore.login(data.access_token, {
        username:     data.username,
        role:         data.role,
        display_name: data.display_name,
      });
      goto('/portfolio');
    } catch (e) {
      error = e.message;
    } finally { loading = false; }
  }
</script>

<div class="max-w-sm mx-auto mt-10">
  <!-- Tab selector -->
  <div class="flex border-b border-gray-200 mb-0">
    <button
      onclick={() => { tab = 'signin'; error = ''; }}
      class="flex-1 py-2 text-xs font-semibold border-b-2 transition-colors
             {tab === 'signin' ? 'border-primary text-primary' : 'border-transparent text-muted hover:text-text'}"
    >Sign In</button>
    <button
      onclick={() => { tab = 'register'; error = ''; }}
      class="flex-1 py-2 text-xs font-semibold border-b-2 transition-colors
             {tab === 'register' ? 'border-primary text-primary' : 'border-transparent text-muted hover:text-text'}"
    >Register</button>
  </div>

  <div class="bg-white rounded-b-lg rounded-tr-lg border border-t-0 border-gray-200 shadow-sm p-6">

    {#if error}
      <div class="mb-3 p-2 rounded bg-red-50 text-red-700 text-xs border border-red-200">{error}</div>
    {/if}

    {#if tab === 'signin'}
      <div class="space-y-3">
        <div>
          <label class="field-label" for="s-user">Username</label>
          <input id="s-user" bind:value={signinForm.username} class="field-input" placeholder="Username"
            onkeydown={(e) => e.key === 'Enter' && signin()} />
        </div>
        <div>
          <label class="field-label" for="s-pass">Password</label>
          <input id="s-pass" type="password" bind:value={signinForm.password} class="field-input" placeholder="Password"
            onkeydown={(e) => e.key === 'Enter' && signin()} />
        </div>
        <button
          onclick={signin}
          disabled={loading || !signinForm.username || !signinForm.password}
          class="btn-primary w-full disabled:opacity-50 mt-1"
        >{loading ? 'Signing in…' : 'Sign In'}</button>
      </div>

    {:else}
      <div class="space-y-3">
        <div>
          <label class="field-label" for="r-user">Username</label>
          <input id="r-user" bind:value={regForm.username} class="field-input" placeholder="Choose a username" />
        </div>
        <div>
          <label class="field-label" for="r-name">Full Name</label>
          <input id="r-name" bind:value={regForm.display_name} class="field-input" placeholder="Full name" />
        </div>
        <div>
          <label class="field-label" for="r-email">Email</label>
          <input id="r-email" type="email" bind:value={regForm.email} class="field-input" placeholder="email@example.com" />
        </div>
        <div>
          <label class="field-label" for="r-phone">Phone</label>
          <input id="r-phone" bind:value={regForm.phone} class="field-input" placeholder="+91 98765 43210" />
        </div>
        <div>
          <label class="field-label" for="r-pan">PAN</label>
          <input id="r-pan" bind:value={regForm.pan} class="field-input" placeholder="ABCDE1234F" maxlength="10" style="text-transform:uppercase" />
        </div>
        <div>
          <label class="field-label" for="r-pass">Password</label>
          <input id="r-pass" type="password" bind:value={regForm.password} class="field-input" placeholder="Min 8 characters" />
        </div>
        <div>
          <label class="field-label" for="r-confirm">Confirm Password</label>
          <input id="r-confirm" type="password" bind:value={regForm.confirm} class="field-input" placeholder="Repeat password" />
        </div>

        <p class="text-[0.6rem] text-muted mt-2">Your account will be pending admin approval after registration.</p>

        <button
          onclick={register}
          disabled={loading || !regForm.username || !regForm.password || !regForm.confirm || !regForm.display_name || !regForm.email}
          class="btn-primary w-full disabled:opacity-50 mt-1"
        >{loading ? 'Creating account…' : 'Register'}</button>
      </div>
    {/if}

  </div>
</div>
