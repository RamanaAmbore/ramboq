import streamlit as st

from src.components import container
from src.helpers.utils import get_path, capitalize
from src.helpers.utils import ramboq_config

nav_labels = ramboq_config['nav_labels']
logo = get_path(ramboq_config['logo'])


def header(nav_container):
    with nav_container:
        create_navbar_desktop_container()
        create_navbar_mobile_container()


def create_navbar_desktop_container():
    with st.container(key='navbar-desktop-container'):
        _, logo_col, _, menu_col, _, signin_col = st.columns([.1, 1.1, .5, 5, .5, 1], gap=None,
                                                             vertical_alignment="center", border=False)

        with logo_col:
            container(st.image, logo, use_container_width=True, key='logo_desktop')
        with menu_col:
            nav_cols = st.columns([1.2, 1, 1.2, 0.9, 0.9, 1.1, 1.1], gap=None, vertical_alignment="center")
            for i, label in enumerate(nav_labels):
                with nav_cols[i]:
                    if label == 'profile':
                        if not st.session_state.auth_status:
                            st.empty()
                    elif st.session_state.active_nav == label:
                        st.button(capitalize(label), type="tertiary", key=f'button-active-desktop', disabled=True)
                    else:
                        st.button(capitalize(label), type="tertiary", key=f'button-{label}-desktop',
                                  on_click=set_active_nav,
                                  args=(label,))


        with signin_col:
            with st.container(key='signin-out'):
                st.button("Sign out" if st.session_state.auth_status else "Sign in/Sign up", type="tertiary",
                          on_click=toggle_signin)


def create_navbar_mobile_container():
    with (st.container(key='navbar-mobile-container')):
        col1, col2 = st.columns([3, 1], gap=None, vertical_alignment="center", border=False)  # Tune proportions

        with col1:
            container(st.image, logo, use_container_width=True, key='logo_mobile')
        with col2:
            with st.popover("☰", use_container_width=True):
                for label in nav_labels + ["Sign in/Sign up"]:
                    if label == 'profile':
                        if not st.session_state.auth_status:
                            st.empty()
                    if label == 'Sign in/Sign up':
                        st.button("Sign out" if st.session_state.auth_status else "Sign in/Sign up",
                                  on_click=toggle_signin,
                                  type="tertiary", key=f'button-{label}-mobile')
                    elif st.session_state.active_nav == label:
                        st.button(capitalize(label), type="tertiary", key=f'button-active-mobile', disabled=True)
                    else:
                        st.button(capitalize(label), type="tertiary", key=f'button-{label}-mobile',
                                  on_click=set_active_nav, args=(label,))


# function to simulate Signin/Sign out action
def toggle_signin():

    st.session_state.signin_pressed = True


def set_active_nav(label):
    params = st.query_params
    parm_label = params.get("page", None)
    if params and parm_label in ramboq_config['nav_labels']:
        if st.session_state.active_nav == parm_label:
            st.session_state.active_nav = label
        else:
            st.session_state.active_nav = parm_label
    else:
        st.session_state.active_nav = label
    st.query_params["page"] = st.session_state.active_nav
    st.session_state.signin_pressed = False


def validate_parms():
    params = st.query_params

    # --- Validation ---
    if params and params.get("page", [None])[0] not in ramboq_config['nav_labels']:
        st.session_state.active_nav = ramboq_config['default_nav_label']
