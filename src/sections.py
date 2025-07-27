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

    nav_labels = ["About", "Market", "Performance", "Update", "Contact", "Login"]
    nav_list_width = [1, 1, 1.1, 1, 1, 1]

    def toggle_login():
        st.session_state.logged_in = not st.session_state.logged_in

    # --- Layout: Logo | Nav/Menu ---

    logo_col,  menu_col = st.columns([1.5, 6], gap="small", vertical_alignment="center")

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
                with st.container():
                    st.markdown("<div class='navbar-desktop'>", unsafe_allow_html=True)
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

                            st.markdown(f"<div style='{btn_style(label)}'>{label}</div>", unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)

            # Mobile popover menu (visible on small screens)
            with mobile_col:
                with st.container():
                    st.markdown("<div class='mobile-popover'>", unsafe_allow_html=True)
                    with st.popover("☰", use_container_width=True):
                        for label in nav_labels:
                            if st.button(label, key=f"mobile-{label}"):
                                st.session_state.nav_active = label
                                if label in ["Login", "Logout"]:
                                    toggle_login()
                                else:
                                    st.session_state.nav = label

                            st.markdown(f"<div style='{btn_style(label)}'>{label}</div>", unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)

    # Content with 10px vertical spacing
    st.markdown("<div>", unsafe_allow_html=True)
    with st.container():
        if st.session_state.nav_active == "About":
            st.write("🏢 Welcome to Ramboq — empowering smarter investments.")
        elif st.session_state.nav_active == "Market":
            st.write("📈 Market analysis and live charts.")
        elif st.session_state.nav_active == "Performance":
            st.write("🧮 Portfolio breakdown and asset overview.")
        elif st.session_state.nav_active == "Update":
            st.write("🧮 Updates coming soon...")
        elif st.session_state.nav_active == "Contact":
            st.write("📞 Contact our team or request a demo.")
    st.markdown("</div>", unsafe_allow_html=True)

    with st.container(key='footer-container'):

        container(
            st.markdown,
            """
            <p style='font-size:15px;'>
                © Rambo Quant Investments LLP
                <span style='color:#007ACC;'> | </span>
                LLDIN00123456
                <span style='color:#007ACC;'> | </span>
                Disclaimer: Investment in markets is subject to risk. Past performance is not indicative of future results.
            </p>
            """,
            key='footer-desktop',
            unsafe_allow_html=True
        )

        container(
            st.markdown,
            """
            <p style='font-size:12px;'>
                © Rambo Quant Investments LLP
                <span style='color:#007ACC;'> | </span>
                LLDIN00123456
                <span style='color:#007ACC;'> | </span>
                Markets carry risk.
            </p>
            """,
            key='footer-mobile',
            unsafe_allow_html=True
        )
