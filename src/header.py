import streamlit as st

from src.about import about
from src.components import container
from src.contact import contact
from src.market import market
from src.performance import performance
from src.update import update
from src.utils import get_path
from src.utils import config

nav_labels = config['nav_labels']


def create_logo(logo_width=300):
    st.image(
        get_path('logo.png'),
        use_container_width="True",
        width=logo_width
    )


body_container = None


def header(nav_container, parm_body_container):
    global body_container
    body_container = parm_body_container

    # Initialize session state for nav highlighting
    if "active_nav" not in st.session_state:
        st.session_state.active_nav = config['default_nav_label']
        set_active_nav(config['default_nav_label'])

    with nav_container:
        create_navbar_desktop_container()
        create_navbar_mobile_container()


def create_navbar_desktop_container():
    with st.container(key='navbar-desktop-container'):
        logo_col, _, menu_col, _, login_col = st.columns([1.5, .5, 5, .5, 1], gap="small",
                                                         vertical_alignment="center")

        with logo_col:
            create_logo()
        with menu_col:
            nav_cols = st.columns([1, 1, 1.2, 1.1, 1.1], gap=None, vertical_alignment="center")
            for i, label in enumerate(nav_labels):
                with nav_cols[i]:
                    if st.session_state.active_nav == label:
                        st.button(label, type="tertiary", key=f'button-active-desktop', disabled=True)
                    else:
                        st.button(label, type="tertiary", key=f'button-{label}-desktop', on_click=set_active_nav,
                                  args=(label,))

        with login_col:
            st.button("Logout" if st.session_state.logged_in else "Login", on_click=toggle_login)


def create_navbar_mobile_container():
    with st.container(key='navbar-mobile-container'):
        col1, col2 = st.columns([4, .25], gap=None, vertical_alignment="center")  # Tune proportions

        with col1:
            create_logo()
        with col2:
            with st.popover("☰", use_container_width=False):
                for label in nav_labels + ["Login"]:
                    if label == 'Login':
                        st.button("Logout" if st.session_state.logged_in else "Login", on_click=toggle_login,
                                  type="tertiary", key=f'button-{label}-mobile')
                    else:
                        st.button(label, type="tertiary", key=f'button-{label}-mobile')


# Dummy function to simulate login/logout action
def toggle_login():
    st.session_state.logged_in = not st.session_state.logged_in


def set_active_nav(label):
    st.session_state.active_nav = label

    # Content with 10px vertical spacing

    if st.session_state.active_nav == "About":
        about(body_container)
    elif st.session_state.active_nav == "Market":
        market(body_container)
    elif st.session_state.active_nav == "Performance":
        performance(body_container)
    elif st.session_state.active_nav == "Update":
        update(body_container)
    elif st.session_state.active_nav == "Contact":
        contact(body_container)
