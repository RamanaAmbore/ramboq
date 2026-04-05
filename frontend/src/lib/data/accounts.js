// Broker accounts cache — loaded from /api/accounts/ on first use.
// Small list (~5 rows) so we just keep it in memory per page load; no
// IndexedDB needed.

import { fetchAccounts } from '$lib/api';

let _accounts = null;
let _loadPromise = null;

export async function loadAccounts() {
  if (_accounts) return _accounts;
  if (_loadPromise) return _loadPromise;
  _loadPromise = (async () => {
    try {
      const data = await fetchAccounts();
      _accounts = (data && data.accounts) || [];
    } catch (e) {
      _accounts = [];
    }
    return _accounts;
  })();
  try { return await _loadPromise; }
  finally { _loadPromise = null; }
}

export function getAccountsSync() {
  return _accounts || [];
}

/** Suggest account IDs matching the given prefix (case-insensitive). */
export function suggestAccounts(prefix, limit = 20) {
  const list = _accounts || [];
  const p = (prefix || '').toUpperCase();
  const matches = list
    .map(a => a.account_id)
    .filter(id => !p || id.toUpperCase().startsWith(p));
  return matches.slice(0, limit);
}

/** Look up an account's masked display name. */
export function getDisplay(accountId) {
  const list = _accounts || [];
  const m = list.find(a => a.account_id === accountId);
  return m ? m.display : accountId;
}
