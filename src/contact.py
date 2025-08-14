import streamlit as st
from src.utils import isd_codes  # YAML-loaded ISD codes
from src.components import create_ruler_white
from src.utils import config
def contact(body_container):
    with body_container:
        with st.container(key='text-container'):
            st.write('Contact Form')
            create_ruler_white()

