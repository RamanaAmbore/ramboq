# Import necessary modules and components

import streamlit as st

# Import custom components and functions from src directory
from src.components import container
from src.utils import get_path


def main_page():
    # Initialize session state
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if "nav" not in st.session_state:
        st.session_state.nav = "About"

    nav_list = ["About", "Market", "Portfolio", "Blog", "Download", "Contact"]
    nav_list_width = [1, 1, 1.1, 1.1, 1, 1]

    def toggle_login():
        st.session_state.logged_in = not st.session_state.logged_in

    # --- Layout: Logo | Nav Buttons | Login ---
    logo, _, navbar, login_out = st.columns([1.5, .5, 6, 1], gap=None,
                                               vertical_alignment="center")
    with st.container(key="nav-container"):
        with logo:
            # Display profile photo
            # container(st.image, get_path('logo8.png'), use_container_width='never', width=300, key='logo-container')
            # --- Layout: Logo | Nav Buttons | Login ---
            st.empty()
        with navbar:
            with st.container(key='nav-button-container'):
                nav_items = st.columns(nav_list_width, gap=None, vertical_alignment="center")
                for i, item in enumerate(nav_list):
                    with nav_items[i]:
                        if st.button(item, key=item):
                            st.session_state.nav = item

        with login_out:
            label = "Logout" if st.session_state.logged_in else "Login"
            if st.button(label, key="login-toggle"):
                toggle_login()

    # Routing to content section
    if st.session_state.nav == "About":
        st.write("🏢 Welcome to Ramboq — empowering smarter investments.")
    elif st.session_state.nav == "Market":
        st.write("📈 Market analysis and live charts.")
    elif st.session_state.nav == "Portfolio":
        st.write("🧮 Portfolio breakdown and asset overview.")
    elif st.session_state.nav == "Blog":
        st.write("🧮 Blog...")
    elif st.session_state.nav == "Download":
        st.write("🧮 Download...")
    elif st.session_state.nav == "Contact":
        st.write("📞 Contact our team or request a demo.")

    container(st.write,
              """© Rambo Quant Investments LLP | LLDIN Number: LLDIN00123456 |  Disclaimer
              : Investment in markets is subject to risk. Past performance is not indicative of future results.
              """, key='custom-footer'
              )
