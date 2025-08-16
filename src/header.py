import streamlit as st
from src.components import container
from src.utils import config
from src.utils import get_path, capitalize

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
            nav_cols = st.columns([1.2, 1, 1.2, 0.9, 0.9, 1.1], gap=None, vertical_alignment="center")
            for i, label in enumerate(nav_labels):
                with nav_cols[i]:
                    if st.session_state.active_nav == label:
                        st.button(capitalize(label), type="tertiary", key=f'button-active-desktop', disabled=True)
                    else:
                        st.button(capitalize(label), type="tertiary", key=f'button-{label}-desktop',
                                  on_click=run_with_spinner,
                                  args=(set_active_nav, label,))

        with login_col:
            with st.container(key='login-out'):
                st.button(capitalize("logout" if st.session_state.logged_in else "login"), type="tertiary",
                          on_click=run_with_spinner, args=(toggle_login,))


def create_navbar_mobile_container():
    with st.container(key='navbar-mobile-container'):
        col1, col2 = st.columns([3, 1], gap=None, vertical_alignment="center", border=False)  # Tune proportions

        with col1:
            container(st.image, logo, use_container_width=True, key='logo_mobile')
        with col2:
            with st.popover("☰", use_container_width=True):
                for label in nav_labels + ["login"]:
                    if label == 'login':
                        st.button(capitalize("logout" if st.session_state.logged_in else "login"),
                                  on_click=run_with_spinner,
                                  args=(toggle_login,),
                                  type="tertiary", key=f'button-{label}-mobile')
                    elif st.session_state.active_nav == label:
                        st.button(capitalize(label), type="tertiary", key=f'button-active-mobile', disabled=True)
                    else:
                        st.button(capitalize(label), type="tertiary", key=f'button-{label}-mobile',
                                  on_click=run_with_spinner,
                                  args=(set_active_nav, label,))


def run_with_spinner(callback, *args):
    with st.spinner("Processing..."):
        callback(*args)


# function to simulate login/logout action
def toggle_login():
    if True:
        st.session_state.logged_in = not st.session_state.logged_in


def set_active_nav(label):
    params = st.query_params
    parm_label = params.get("page", None)
    if params and parm_label in config['nav_labels']:
        if st.session_state.active_nav == parm_label:
            st.session_state.active_nav = label
        else:
            st.session_state.active_nav = parm_label
    else:
        st.session_state.active_nav = label
    st.query_params["page"] = st.session_state.active_nav


def validate_parms():
    params = st.query_params

    # --- Validation ---
    if params and params.get("page", [None])[0] not in config['nav_labels']:
        st.session_state.active_nav = config['default_nav_label']
