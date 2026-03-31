from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

from src.constants import holdings_config, margins_config, positions_config
from src.helpers.date_time_utils import timestamp_est
from src.helpers.utils import get_nearest_time, add_comma_to_df_numbers, config
from src.utils_streamlit import fetch_positions, fetch_holdings, fetch_margins, style_dataframe

_TAB_KEYS = ["funds", "holdings", "positions"]
_TAB_LABELS = ["Funds", "Holdings", "Positions"]


def performance():
    with st.container(key="body-container"):
        _performance_content()


@st.fragment(run_every=60)
def _performance_content():
    refresh_time = get_nearest_time(interval=config.get('performance_refresh_interval', 5))
    ist_display = datetime.strptime(refresh_time, "%d-%b-%y %H:%M").strftime("%a, %B %d, %Y, %I:%M %p")
    est_display = timestamp_est().strftime("%a, %B %d, %Y, %I:%M %p")
    st.write(f"**Refreshed at {ist_display} IST | {est_display} EST**")

    # Determine active tab from URL param
    url_tab = st.query_params.get("tab", _TAB_KEYS[0])
    if url_tab not in _TAB_KEYS:
        url_tab = _TAB_KEYS[0]
    tab_index = _TAB_KEYS.index(url_tab)

    tabs = st.tabs(_TAB_LABELS)

    # Fetch margins and positions in parallel; holdings depends on margins result
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_margins = ex.submit(fetch_margins, refresh_time)
        f_positions = ex.submit(fetch_positions, refresh_time)
        df_margins = f_margins.result()
        df_holdings, sum_holdings = fetch_holdings(refresh_time, df_margins)
        df_positions, sum_positions = f_positions.result()

    with tabs[0]:
        st.dataframe(style_dataframe(add_comma_to_df_numbers(df_margins)),
                     hide_index=True, column_config=margins_config)

    with tabs[1]:
        st.write("**Summary**")
        st.dataframe(style_dataframe(add_comma_to_df_numbers(sum_holdings)),
                     hide_index=True, column_config=holdings_config)
        for account in df_holdings['account'].unique():
            st.write(f"**{account}**")
            acct_df = df_holdings[df_holdings['account'] == account]
            st.dataframe(style_dataframe(add_comma_to_df_numbers(acct_df)),
                         hide_index=True, column_config=holdings_config)
        st.write("**All Accounts — Holdings**")
        st.dataframe(style_dataframe(add_comma_to_df_numbers(df_holdings)),
                     hide_index=True, column_config=holdings_config)

    with tabs[2]:
        st.write("**Summary**")
        st.dataframe(style_dataframe(add_comma_to_df_numbers(sum_positions)),
                     hide_index=True, column_config=positions_config)
        for account in df_positions['account'].unique():
            st.write(f"**{account}**")
            acct_df = df_positions[df_positions['account'] == account]
            st.dataframe(style_dataframe(add_comma_to_df_numbers(acct_df)),
                         hide_index=True, column_config=positions_config)
        st.write("**All Accounts — Positions**")
        st.dataframe(style_dataframe(add_comma_to_df_numbers(df_positions)),
                     hide_index=True, column_config=positions_config)

    # Sync tab selection with URL ?tab= param
    tab_keys_json = str(_TAB_KEYS).replace("'", '"')
    components.html(f"""
<script>
(function() {{
    var tabKeys = {tab_keys_json};
    var targetIdx = {tab_index};

    function init() {{
        var container = window.parent.document.querySelector('[data-testid="stTabs"]');
        if (!container) {{ setTimeout(init, 50); return; }}
        var btns = container.querySelectorAll('[role="tab"]');
        if (btns.length < tabKeys.length) {{ setTimeout(init, 50); return; }}

        // Ensure ?tab= is always present in the URL on page load
        var url = new URL(window.parent.location.href);
        if (!url.searchParams.has('tab')) {{
            url.searchParams.set('tab', tabKeys[targetIdx]);
            window.parent.history.replaceState(null, '', url.toString());
        }}

        // Auto-select correct tab on page load (aria-selected check prevents infinite loop)
        if (btns[targetIdx] && btns[targetIdx].getAttribute('aria-selected') !== 'true') {{
            btns[targetIdx].click();
        }}

        // Update URL when user clicks a tab
        btns.forEach(function(btn, i) {{
            btn.addEventListener('click', function() {{
                var url = new URL(window.parent.location.href);
                url.searchParams.set('tab', tabKeys[i]);
                window.parent.history.replaceState(null, '', url.toString());
            }});
        }});
    }}
    init();
}})();
</script>
""", height=0)
