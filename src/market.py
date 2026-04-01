import streamlit as st

from src.helpers.utils import get_cycle_date, config
from src.utils_streamlit import get_market_update


def market():
    with st.container(key="body-container"):
        with st.container(key='text-container'):
            _market_content()


@st.fragment(run_every=300)
def _market_content():
    placeholder = st.empty()
    content = get_market_update(get_cycle_date())
    placeholder.write(content)
