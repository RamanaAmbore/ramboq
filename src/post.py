import streamlit as st
from src.components import create_ruler_white
from src.utils import config


def post(body_container):
    with body_container:
        with st.container(key='text-container'):
            st.write(config['post'])
            create_ruler_white()
