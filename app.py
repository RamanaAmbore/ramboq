# Import necessary modules and components
import random

import streamlit as st

from src.body import body
# Import custom components and functions from the src directory
from src.components import markdown  # Functions for setting background and styling
from src.footer import footer
from src.header import create_navbar_desktop_container, create_navbar_mobile_container
from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import get_path, css_style, \
    ramboq_config, nav_plus_signin, \
    default_nav_label, nav_plus_signin_out, \
    capitalize, signin_label, signout_label, \
    signin_label_val, signout_label_val  # Utility functions for styling, accessing profile data, and image paths
from src.utils_streamlit import get_image_bin_file

logger = get_logger(__name__)


# Define the initial setup function to configure the Streamlit app
def initial_setup():
    # Load the favicon image from the specified file path
    favicon_path = get_path(ramboq_config['favicon'])

    # Set the page configuration for the Streamlit app
    st.set_page_config(
        page_title="Rambo Quant Investments",  # Set the page title dynamically
        page_icon=favicon_path,  # Use the favicon image
        layout="centered"  # Use a wide layout for the app
    )

    # Set the background image for the page
    if 'css_style' not in st.session_state:
        bin_str = get_image_bin_file('nav_image.png')
        st.session_state.css_style = css_style.replace('nav_image', bin_str)

    # Apply CSS styling to the page content
    markdown(st.session_state.css_style, css=True)

    initialize_app_state()


def initialize_app_state():
    # Initialize session state
    if "first_time" not in st.session_state:
        st.session_state.first_time = False

        st.session_state.signin_pressed = False
        st.session_state.signout_pressed = False
        st.session_state.reg_completed = False
        st.session_state.user_prof_updated = False
        st.session_state.user_validated = False
        st.session_state.user_locked = False
        st.session_state.prof_label = ""


        params = st.query_params
        parm_label = params.get("page", None)

        if params and parm_label in nav_plus_signin:
            st.session_state.active_nav = parm_label
        else:
            st.session_state.active_nav = default_nav_label

        st.session_state.nav_map = {val: capitalize(val) for val in nav_plus_signin_out}
        st.session_state.nav_map['profile'] = ""
        st.session_state.nav_map[signin_label] = signin_label_val
        st.session_state.nav_map[signout_label] = signout_label_val

        st.query_params["page"] = st.session_state.active_nav


# Main function to execute the initial setup and generate different sections of the profile page
if __name__ == '__main__':
    initial_setup()  # Call the setup function to configure the app

    with st.container(key="navbar-container"):
        create_navbar_desktop_container()
        create_navbar_mobile_container()

    body_container = st.container(key="body-container")
    footer_container = st.container(key='footer-container')

    body(body_container)
    footer(footer_container)
