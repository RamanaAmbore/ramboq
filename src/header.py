import streamlit as st

from src.components import container
from src.utils import get_path


def header():
    # Initialize session state
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "nav" not in st.session_state:
        st.session_state.nav = "About"
    nav_labels = ["About", "Market", "Performance", "Update", "Contact", "Login"]
    nav_list_width = [1, 1, 1.1, 1, 1, 1]

    def toggle_login():
        st.session_state.logged_in = not st.session_state.logged_in

    # --- Layout: Logo | Nav/Menu ---
    logo_col, menu_col = st.columns([1.5, 6], gap="small", vertical_alignment="center")
    with st.container(key='nav-container'):
        with logo_col:
            container(
                st.image,
                get_path('logo7.png'),
                use_container_width='None',
                width=200,
                key='logo-container'
            )

        # Initialize session state for nav highlighting
        if "nav_active" not in st.session_state:
            st.session_state.nav_active = None

        # Define styling for active and inactive buttons
        btn_style = lambda label: (
            "background-color:#007ACC; color:white; font-weight:bold; border:none; padding:6px 12px; border-radius:4px;"
            if st.session_state.nav_active == label else
            "background-color:transparent; color:black; padding:6px 12px;"
        )

        with menu_col:
            nav_col, mobile_col = st.columns([4, 1], gap="small")  # Wider desktop, narrow hamburger

            # Desktop navbar (visible on large screens)
            with nav_col:
                with st.container(key='navbar-desktop'):

                    nav_labels = nav_labels[:-1] + ["Logout" if st.session_state.logged_in else "Login"]
                    nav_cols = st.columns(len(nav_labels), gap="small")

                    for i, label in enumerate(nav_labels):
                        with nav_cols[i]:
                            if st.button(label, key=f"desktop-{label}"):
                                st.session_state.nav_active = label
                                if label in ["Login", "Logout"]:
                                    toggle_login()
                                else:
                                    st.session_state.nav = label

            # Mobile popover menu (visible on small screens)
            with mobile_col:
                with st.container(key='mobile-popover'):
                    with st.popover("☰", use_container_width=True):
                        for label in nav_labels:
                            if st.button(label, key=f"mobile-{label}"):
                                st.session_state.nav_active = label
                                if label in ["Login", "Logout"]:
                                    toggle_login()
                                else:
                                    st.session_state.nav = label
