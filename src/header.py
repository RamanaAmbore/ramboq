import streamlit as st

from src.components import container
from src.utils import get_path

nav_labels = ["About", "Market", "Performance", "Update", "Contact"]


def create_logo(logo_col, key='logo_container'):
    with logo_col:
        container(
            st.image,
            get_path('logo7.png'),
            use_container_width="True",
            width=300,
            key=key
        )


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
        logo_col, _, menu_col, _, login_col = st.columns([1.5, .25, 5, .25, 1], gap="small",
                                                         vertical_alignment="center")

        with logo_col:
            container(
                st.image,
                get_path('logo7.png'),
                use_container_width="True",
                width=300,
                key='logo_container'
            )


        with menu_col:
            nav_cols = st.columns(len(nav_labels), gap="small")

            for i, label in enumerate(nav_labels):
                with nav_cols[i]:
                    st.button(label, key=f'button-{label}-desktop')
        with login_col:
            st.button("Logout" if st.session_state.logged_in else "Login")


def create_navbar_mobile_container():
    with st.container(key='navbar-mobile-container'):
        # Adjust column proportions for better fit
        logo_col, menu_col = st.columns([0.65, .35], gap="small",vertical_alignment="center")

        with logo_col:
            container(
                st.image,
                get_path('logo7.png'),
                use_container_width="False",
                width=200,
                key='logo_container-1'
            )
        with menu_col:
            # Avoid inner nesting; align popover directly
            with st.popover("☰"):  # shows inline now
                nav_list = nav_labels + ['Login']
                for label in nav_list:
                    st.button(label, key=f'button-{label}-mobile')

