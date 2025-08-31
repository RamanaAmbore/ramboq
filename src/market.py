import streamlit as st

from src.helpers.utils import get_cycle_date
from src.utils_streamlit import get_market_update


def market():
    with st.container(key="body-container"):
        with st.container(key='text-container'):
            placeholder = st.empty()  # reserve placeholder spot

    # Generate content which takes time
    content = get_market_update(get_cycle_date())

    # Update the placeholder with the generated content
    placeholder.write(content)
