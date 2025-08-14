import streamlit as st


def update(body_container):
    with body_container:
        st.write("Content for the Updates page.")
