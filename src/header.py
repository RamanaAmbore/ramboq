import streamlit as st

from src.utils import config
from src.components import container
from src.utils import get_path

nav_labels = config['nav_labels']
logo = get_path(config['logo'])


def header(nav_container):
    with nav_container:
        create_navbar_desktop_container()
        create_navbar_mobile_container()


def create_navbar_desktop_container():
    with st.container(key='navbar-desktop-container'):
        _, logo_col, _, menu_col, _, login_col = st.columns([.1, 1.1, .5, 5, .5, 1], gap=None,
                                                         vertical_alignment="center", border=False)

        with logo_col:
            container(st.image, logo, use_container_width=True, key='logo_desktop')
        with menu_col:
            nav_cols = st.columns([1.2, 1, 1.2, 1.1, 1.1], gap=None, vertical_alignment="center")
            for i, label in enumerate(nav_labels):
                with nav_cols[i]:
                    if st.session_state.active_nav == label:
                        st.button(label, type="tertiary", key=f'button-active-desktop', disabled=True)
                    else:
                        st.button(label, type="tertiary", key=f'button-{label}-desktop', on_click=set_active_nav,
                                  args=(label,))

        with login_col:
            with st.container(key='login-out'):
                st.button("Logout" if st.session_state.logged_in else "Login", type="tertiary", on_click=toggle_login)


def create_navbar_mobile_container():
    with st.container(key='navbar-mobile-container'):
        col1, col2 = st.columns([3,1], gap=None, vertical_alignment="center", border=False)  # Tune proportions

        with col1:
            container(st.image, logo, use_container_width=True, key='logo_mobile')
        with col2:
            with st.popover("☰", use_container_width=True):
                for label in nav_labels + ["Login"]:
                    if label == 'Login':
                        st.button("Logout" if st.session_state.logged_in else "Login", on_click=toggle_login,
                                  type="tertiary", key=f'button-{label}-mobile')
                    elif st.session_state.active_nav == label:
                        st.button(label, type="tertiary", key=f'button-active-mobile', disabled=True)
                    else:
                        st.button(label, type="tertiary", key=f'button-{label}-mobile', on_click=set_active_nav,
                                  args=(label,))


# Dummy function to simulate login/logout action
def toggle_login():
    if True:
        st.session_state.logged_in = not st.session_state.logged_in


def set_active_nav(label):
    st.session_state.active_nav = label
