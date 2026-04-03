<script>
  let form = { name: '', email: '', message: '' };
  let submitting = false;
  let success    = '';
  let error      = '';

  async function submit() {
    submitting = true;
    success    = '';
    error      = '';
    try {
      const res = await fetch('/api/contact/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(d.detail || 'Failed to send message');
      success = d.detail || 'Your message has been sent. We will get back to you shortly.';
      form = { name: '', email: '', message: '' };
    } catch (e) {
      error = /** @type {Error} */ (e).message || 'Failed to send message. Please try again.';
    } finally {
      submitting = false;
    }
  }
</script>
<svelte:head>
  <title>Contact | RamboQuant Analytics</title>
  <meta name="description" content="Get in touch with RamboQuant Analytics LLP." />
</svelte:head>


<div class="w-full">
  <div class="bg-white rounded-lg border border-gray-200 shadow-sm p-5 pt-4">
    <h1 class="page-heading">Contact</h1>
    {#if success}
      <div class="mb-4 p-3 rounded bg-green-50 text-green-700 text-sm border border-green-200">{success}</div>
    {/if}
    {#if error}
      <div class="mb-4 p-3 rounded bg-red-50 text-red-700 text-sm border border-red-200">{error}</div>
    {/if}

    <div class="space-y-4">
      <div>
        <label class="field-label" for="c-name">Name</label>
        <input id="c-name" bind:value={form.name} class="field-input" placeholder="Your name" />
      </div>
      <div>
        <label class="field-label" for="c-email">Email</label>
        <input id="c-email" type="email" bind:value={form.email} class="field-input" placeholder="you@example.com" />
      </div>
      <div>
        <label class="field-label" for="c-msg">Message</label>
        <textarea
          id="c-msg"
          bind:value={form.message}
          class="field-input min-h-[120px] resize-y"
          placeholder="How can we help you?"
        ></textarea>
      </div>
      <button
        onclick={submit}
        disabled={submitting || !form.name || !form.email || !form.message}
        class="btn-primary w-full disabled:opacity-50"
      >
        {submitting ? 'Sending…' : 'Send Message'}
      </button>
    </div>
  </div>
</div>
