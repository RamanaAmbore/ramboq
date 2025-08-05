# Import necessary modules and components
import logging  # Module for logging events and messages

import streamlit as st
from PIL import Image  # PIL module for image handling

# Import custom components and functions from the src directory
from src.components import markdown  # Functions for setting background and styling
from src.footer import footer
from src.header import header, set_active_nav
from src.logger import log_setup  # Custom logging setup
from src.utils import css_style, get_path, \
    config  # Utility functions for styling, accessing profile data, and image paths


# Define the initial setup function to configure the Streamlit app
def initial_setup():
    # Initialize the logger in the session state if not already present
    if 'logger' not in st.session_state:
        st.session_state.logger = log_setup()  # Set up the logger
        logging.info('Logging setup')  # Log an informational message

    # Load the favicon image from the specified file path
    favicon = Image.open(get_path("favicon.ico"))

    # Set the page configuration for the Streamlit app
    st.set_page_config(
        page_title="Rambo Quant Investments",  # Set the page title dynamically
        page_icon=favicon,  # Use the favicon image
        layout="centered"  # Use a wide layout for the app
    )

    # Apply CSS styling to the page content
    markdown(css_style, css=True)

    # Set the background image for the page
    # set_png_as_page_bg('background.png')


def initialize_app_state():
    # Initialize session state
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False


# Main function to execute the initial setup and generate different sections of the profile page
if __name__ == '__main__':
    initial_setup()  # Call the setup function to configure the app

    initialize_app_state()

    nav_container = st.container(key="navbar-container")
    body_container = st.container(key="body-container")
    footer_container = st.container(key='footer-container')

    header(nav_container, body_container)

    footer(footer_container)
