import streamlit as st

from src.helpers.utils import get_cycle_date
from src.utils_streamlit import get_market_update


def market():
    with st.container(key="body-container"):
        with st.container(key='text-container'):
            placeholder = st.empty()  # reserve placeholder spot

            with st.spinner("Fetching response from GenAI…"):
                content = get_market_update(get_cycle_date())
                # After content is ready, update the placeholder
                placeholder.write(content)
