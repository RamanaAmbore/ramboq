# Import necessary modules and components
import streamlit as st

from src.body import body
from src.utils_streamlit import get_image_bin_file
# Import custom components and functions from the src directory
from src.components import markdown  # Functions for setting background and styling
from src.footer import footer
from src.header import header
from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import get_path, css_style,\
    ramboq_config  # Utility functions for styling, accessing profile data, and image paths

logger = get_logger(__name__)


# Define the initial setup function to configure the Streamlit app
def initial_setup():
    global css_style

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
        st.session_state.user_validated = False
        st.session_state.validated = False
        st.session_state.user_locked = False
        st.session_state.user_prof_updated = False



        params = st.query_params
        parm_label = params.get("page", None)

        if params and parm_label in ramboq_config['nav_labels']:
            st.session_state.active_nav = parm_label
        else:
            st.session_state.active_nav = ramboq_config['default_nav_label']
        # st.session_state.prev_active_nav = st.session_state.active_nav
        st.query_params["page"] = st.session_state.active_nav


# Main function to execute the initial setup and generate different sections of the profile page
if __name__ == '__main__':
    initial_setup()  # Call the setup function to configure the app

    nav_container = st.container(key="navbar-container")
    body_container = st.container(key="body-container")
    footer_container = st.container(key='footer-container')

    header(nav_container)
    body(body_container)
    footer(footer_container)
