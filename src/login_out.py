import streamlit as st
from components.layout import render_layout

layout, _ = render_layout("Login")
with layout:
    st.title("🔐 Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Submit"):
        if username and password:
            st.session_state.is_logged_in = True
            st.success("Logged in successfully.")
            st.experimental_rerun()
        else:
            st.error("Please enter both username and password.")