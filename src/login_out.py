import streamlit as st


def signin_out():
    st.title("🔐 Sign in/Sign up")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Submit"):
        if username and password:
            st.session_state.is_logged_in = True
            st.success("Logged in successfully.")
            st.experimental_rerun()
        else:
            st.error("Please enter both username and password.")
