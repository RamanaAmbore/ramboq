import streamlit as st

from src.components import container
from src.utils import get_path

nav_labels = ["About", "Market", "Performance", "Update", "Contact"]


def header():
    # Initialize session state
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    # Initialize session state for nav highlighting
    if "nav_active" not in st.session_state:
        st.session_state.nav_active = "Market"

    with st.container(key="navbar-container"):
        create_navbar_desktop_container()
        create_navbar_mobile_container()


def create_navbar_desktop_container():
    with st.container(key='navbar-desktop-container'):
        logo_col, _, menu_col, _, login_col = st.columns([1.5, .5, 5, .5, 1], gap="small",
                                                         vertical_alignment="center")

        with logo_col:
                st.image(
                get_path('logo.png'),
                use_container_width="False",
                width=300)

        with menu_col:
            with st.container(key="nav-buttons"):
                nav_cols = st.columns([1,1,1.2,1.1,1.1], gap=None, vertical_alignment="center")

                for i, label in enumerate(nav_labels):
                    with nav_cols[i]:
                        st.button(label, key=f'button-{label}-desktop')
        with login_col:
            st.button("Logout" if st.session_state.logged_in else "Login")


def create_navbar_mobile_container():
    with st.container(key='navbar-mobile-container'):
            col1, col2 = st.columns([4, .25],gap=None, vertical_alignment="center")  # Tune proportions

            with col1:
                        st.image(
                        get_path('logo.png'),
                        use_container_width="True",
                        width=300,
                        )


            with col2:
                    with st.popover("☰", use_container_width=True):
                        for label in nav_labels + ["Login"]:
                            st.button(label,key=f'button-{label}-mobile')


