import streamlit as st

from src.components import container
from src.helpers.utils import nav_plus_signin, logo, nav_labels
from src.helpers.utils import ramboq_config


def create_navbar():
    with st.container(key="navbar-container"):
        create_navbar_desktop_container()
        create_navbar_mobile_container()


def conf_nav_label(label="", type='desktop'):
    if st.session_state.active_nav == label:
        st.button(st.session_state.nav_map[label], type="tertiary", key=f'button-active-{type}', disabled=True)
    else:
        if st.session_state.nav_map[label] == "":
            st.empty()
        else:
            st.button(st.session_state.nav_map[label], type="tertiary", key=f'button-{label}-{type}',
                      on_click=set_active_nav, args=(label,))


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
                    conf_nav_label(label, type='desktop')

        with signin_col:
            with st.container(key='signin-out'):
                st.button(st.session_state.nav_map['signin'], type="tertiary", on_click=set_active_nav,
                          args=('signin',))


def create_navbar_mobile_container():
    with (st.container(key='navbar-mobile-container')):
        col1, col2 = st.columns([3, 1], gap=None, vertical_alignment="center", border=False)  # Tune proportions

        with col1:
            container(st.image, logo, use_container_width=True, key='logo_mobile')
        with col2:
            with st.popover("☰", use_container_width=True):
                for label in nav_plus_signin:
                    conf_nav_label(label, type='mobile')


def set_active_nav(label):
    params = st.query_params
    parm_label = params.get("page", None)
    if params and parm_label in nav_plus_signin:
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
    if params and params.get("page", [None])[0] not in ramboq_config['nav_labels']:
        st.session_state.active_nav = ramboq_config['default_nav_label']
