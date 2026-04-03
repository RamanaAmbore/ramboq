<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores';
  import { fetchUsers, approveUser, rejectUser, updateUser, createUser } from '$lib/api';

  let users    = $state([]);
  let loading  = $state(true);
  let error    = $state('');
  let success  = $state('');
  let editing  = $state(null);
  let editForm = $state(/** @type {Record<string,any>} */ ({}));
  let showCreate = $state(false);
  let createForm = $state({ username: '', password: '', display_name: '', email: '', phone: '', role: 'partner', contribution: 0, share_pct: 0, is_approved: true });
  let creating = $state(false);

  async function load() {
    loading = true; error = ''; success = '';
    try {
      const data = await fetchUsers();
      users = data.users ?? [];
    } catch (e) {
      error = e.message;
    } finally { loading = false; }
  }

  async function approve(/** @type {string} */ username) {
    try { await approveUser(username); success = `${username} approved`; await load(); }
    catch (e) { error = e.message; }
  }

  async function reject(/** @type {string} */ username) {
    try { await rejectUser(username); success = `${username} rejected`; await load(); }
    catch (e) { error = e.message; }
  }

  async function doCreate() {
    creating = true; error = '';
    if (createForm.password.length < 8) { error = 'Password must be at least 8 characters'; creating = false; return; }
    try {
      await createUser(createForm);
      success = `User ${createForm.username} created. Share the password securely.`;
      showCreate = false;
      createForm = { username: '', password: '', display_name: '', email: '', phone: '', role: 'partner', contribution: 0, share_pct: 0, is_approved: true };
      await load();
    } catch (e) { error = e.message; }
    finally { creating = false; }
  }

  function startEdit(/** @type {any} */ user) {
    editing = user.username;
    editForm = {
      display_name:    user.display_name,
      role:            user.role,
      email:           user.email ?? '',
      phone:           user.phone ?? '',
      pan:             user.pan ?? '',
      date_of_birth:   user.date_of_birth ?? '',
      kyc_verified:    user.kyc_verified,
      address_line1:   user.address_line1 ?? '',
      address_line2:   user.address_line2 ?? '',
      city:            user.city ?? '',
      state:           user.state ?? '',
      pincode:         user.pincode ?? '',
      contribution:    user.contribution,
      contribution_date: user.contribution_date ?? '',
      share_pct:       user.share_pct,
      bank_name:       user.bank_name ?? '',
      bank_account:    user.bank_account ?? '',
      bank_ifsc:       user.bank_ifsc ?? '',
      nominee_name:    user.nominee_name ?? '',
      nominee_relation: user.nominee_relation ?? '',
      nominee_phone:   user.nominee_phone ?? '',
      join_date:       user.join_date ?? '',
      notes:           user.notes ?? '',
    };
  }

  function cancelEdit() { editing = null; }

  async function saveEdit() {
    try {
      await updateUser(editing, editForm);
      success = `${editing} updated`;
      editing = null;
      await load();
    } catch (e) { error = e.message; }
  }

  onMount(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') { goto('/signin'); return; }
    load();
  });
</script>

<div class="bg-white rounded-lg border border-gray-200 shadow-sm p-5 pt-4">
  <div class="flex items-center justify-between mb-1">
    <h1 class="page-heading mb-0 border-0">User Management</h1>
    <button onclick={() => showCreate = !showCreate} class="btn-primary text-[0.65rem] py-1 px-3">
      {showCreate ? 'Cancel' : 'Create User'}
    </button>
  </div>
  <div class="border-b border-[#2f4f4f] mb-4"></div>

  {#if success}
    <div class="mb-3 p-2 rounded bg-green-50 text-green-700 text-xs border border-green-200">{success}</div>
  {/if}
  {#if error}
    <div class="mb-3 p-2 rounded bg-red-50 text-red-700 text-xs border border-red-200">{error}</div>
  {/if}

  <!-- Create User Form -->
  {#if showCreate}
    <div class="rounded-lg border border-gray-200 p-4 mb-4 bg-gray-50">
      <h3 class="section-heading mb-3">New User</h3>
      <div class="grid grid-cols-2 md:grid-cols-3 gap-3">
        <div><label class="field-label">Username</label><input bind:value={createForm.username} class="field-input" placeholder="login username" /></div>
        <div><label class="field-label">Password</label><input type="password" bind:value={createForm.password} class="field-input" placeholder="min 8 chars" /></div>
        <div><label class="field-label">Full Name</label><input bind:value={createForm.display_name} class="field-input" /></div>
        <div><label class="field-label">Email</label><input type="email" bind:value={createForm.email} class="field-input" /></div>
        <div><label class="field-label">Phone</label><input bind:value={createForm.phone} class="field-input" /></div>
        <div><label class="field-label">Role</label>
          <select bind:value={createForm.role} class="field-input">
            <option value="partner">Partner</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <div><label class="field-label">Contribution (₹)</label><input type="number" bind:value={createForm.contribution} class="field-input" /></div>
        <div><label class="field-label">Profit Share (%)</label><input type="number" step="0.1" bind:value={createForm.share_pct} class="field-input" /></div>
        <div class="flex items-end">
          <button onclick={doCreate} disabled={creating || !createForm.username || !createForm.password}
            class="btn-primary text-[0.65rem] py-1.5 px-4 disabled:opacity-50">
            {creating ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  {/if}

  {#if loading}
    <div class="text-center text-text/40 text-xs animate-pulse py-8">Loading users…</div>
  {:else if !users.length}
    <p class="text-xs text-text/50">No users registered.</p>
  {:else}
    <div class="space-y-3">
      {#each users as user}
        <div class="rounded-lg border border-gray-200 p-3">
          <!-- Header row -->
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center flex-wrap gap-1.5">
              <span class="font-semibold text-xs text-primary">{user.display_name}</span>
              <span class="text-xs text-muted">@{user.username}</span>
              <span class="text-[0.6rem] text-muted font-mono">{user.account_id}</span>
              <span class="px-1.5 py-0.5 rounded text-[0.6rem] font-semibold uppercase
                {user.role === 'admin' ? 'bg-amber-100 text-amber-700' : 'bg-teal-50 text-teal-700'}">
                {user.role}
              </span>
              {#if !user.is_approved}
                <span class="px-1.5 py-0.5 rounded bg-orange-100 text-orange-700 text-[0.6rem] font-semibold uppercase">Pending</span>
              {/if}
              {#if !user.is_active}
                <span class="px-1.5 py-0.5 rounded bg-red-100 text-red-700 text-[0.6rem] font-semibold uppercase">Inactive</span>
              {/if}
              {#if user.kyc_verified}
                <span class="px-1.5 py-0.5 rounded bg-green-100 text-green-700 text-[0.6rem] font-semibold uppercase">KYC</span>
              {/if}
            </div>
            <div class="flex gap-1.5">
              {#if !user.is_approved && user.is_active && user.role !== 'admin'}
                <button onclick={() => approve(user.username)} class="btn-primary text-[0.65rem] py-1 px-2">Approve</button>
                <button onclick={() => reject(user.username)} class="btn-secondary text-[0.65rem] py-1 px-2">Reject</button>
              {/if}
              {#if editing !== user.username}
                <button onclick={() => startEdit(user)} class="btn-secondary text-[0.65rem] py-1 px-2">Edit</button>
              {/if}
            </div>
          </div>

          {#if editing !== user.username}
            <!-- Read-only summary -->
            <div class="grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-1 text-xs text-text/70">
              <div><span class="text-muted">Email:</span> {user.email || '—'}</div>
              <div><span class="text-muted">Phone:</span> {user.phone || '—'}</div>
              <div><span class="text-muted">PAN:</span> {user.pan || '—'}</div>
              <div><span class="text-muted">Contribution:</span> ₹{user.contribution.toLocaleString('en-IN')}</div>
              <div><span class="text-muted">Contributed:</span> {user.contribution_date || '—'}</div>
              <div><span class="text-muted">Share:</span> {user.share_pct}%</div>
              <div><span class="text-muted">Joined:</span> {user.join_date || '—'}</div>
              <div><span class="text-muted">Nominee:</span> {user.nominee_name || '—'}</div>
            </div>
          {:else}
            <!-- Edit form -->
            <div class="mt-3 space-y-4">
              <div>
                <h3 class="section-heading mb-2">Personal</h3>
                <div class="grid grid-cols-2 md:grid-cols-3 gap-3">
                  <div><label class="field-label">Display Name</label><input bind:value={editForm.display_name} class="field-input" /></div>
                  <div><label class="field-label">Email</label><input type="email" bind:value={editForm.email} class="field-input" /></div>
                  <div><label class="field-label">Phone</label><input bind:value={editForm.phone} class="field-input" /></div>
                  <div><label class="field-label">PAN</label><input bind:value={editForm.pan} class="field-input" maxlength="10" style="text-transform:uppercase" /></div>
                  <div><label class="field-label">Date of Birth</label><input type="date" bind:value={editForm.date_of_birth} class="field-input" /></div>
                  <div class="flex items-end gap-2">
                    <label class="field-label">KYC Verified</label>
                    <input type="checkbox" bind:checked={editForm.kyc_verified} class="mt-1" />
                  </div>
                </div>
              </div>
              <div>
                <h3 class="section-heading mb-2">Address</h3>
                <div class="grid grid-cols-2 md:grid-cols-3 gap-3">
                  <div class="col-span-2 md:col-span-3"><label class="field-label">Address Line 1</label><input bind:value={editForm.address_line1} class="field-input" /></div>
                  <div class="col-span-2 md:col-span-3"><label class="field-label">Address Line 2</label><input bind:value={editForm.address_line2} class="field-input" /></div>
                  <div><label class="field-label">City</label><input bind:value={editForm.city} class="field-input" /></div>
                  <div><label class="field-label">State</label><input bind:value={editForm.state} class="field-input" /></div>
                  <div><label class="field-label">Pincode</label><input bind:value={editForm.pincode} class="field-input" maxlength="6" /></div>
                </div>
              </div>
              <div>
                <h3 class="section-heading mb-2">Investment</h3>
                <div class="grid grid-cols-2 md:grid-cols-3 gap-3">
                  <div><label class="field-label">Role</label>
                    <select bind:value={editForm.role} class="field-input">
                      <option value="partner">Partner</option>
                      <option value="admin">Admin</option>
                    </select>
                  </div>
                  <div><label class="field-label">Contribution (₹)</label><input type="number" bind:value={editForm.contribution} class="field-input" /></div>
                  <div><label class="field-label">Contribution Date</label><input type="date" bind:value={editForm.contribution_date} class="field-input" /></div>
                  <div><label class="field-label">Profit Share (%)</label><input type="number" step="0.1" bind:value={editForm.share_pct} class="field-input" /></div>
                  <div><label class="field-label">Join Date</label><input type="date" bind:value={editForm.join_date} class="field-input" /></div>
                </div>
              </div>
              <div>
                <h3 class="section-heading mb-2">Bank Details</h3>
                <div class="grid grid-cols-2 md:grid-cols-3 gap-3">
                  <div><label class="field-label">Bank Name</label><input bind:value={editForm.bank_name} class="field-input" /></div>
                  <div><label class="field-label">Account Number</label><input bind:value={editForm.bank_account} class="field-input" /></div>
                  <div><label class="field-label">IFSC</label><input bind:value={editForm.bank_ifsc} class="field-input" /></div>
                </div>
              </div>
              <div>
                <h3 class="section-heading mb-2">Nominee</h3>
                <div class="grid grid-cols-2 md:grid-cols-3 gap-3">
                  <div><label class="field-label">Name</label><input bind:value={editForm.nominee_name} class="field-input" /></div>
                  <div><label class="field-label">Relation</label><input bind:value={editForm.nominee_relation} class="field-input" placeholder="Spouse, Child, etc." /></div>
                  <div><label class="field-label">Phone</label><input bind:value={editForm.nominee_phone} class="field-input" /></div>
                </div>
              </div>
              <div>
                <h3 class="section-heading mb-2">Notes</h3>
                <textarea bind:value={editForm.notes} class="field-input" rows="2" placeholder="Admin notes…"></textarea>
              </div>
              <div class="flex gap-2 pt-1">
                <button onclick={saveEdit} class="btn-primary text-[0.65rem] py-1 px-4">Save</button>
                <button onclick={cancelEdit} class="btn-secondary text-[0.65rem] py-1 px-4">Cancel</button>
              </div>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>
