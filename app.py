# Import necessary modules and components
import logging  # Module for logging events and messages

import streamlit as st
from PIL import Image  # PIL module for image handling
from src.utils import get_image_bin_file  # Functions for setting background and styling

from src.body import body
from src.components import set_png_as_page_bg, markdown
# Import custom components and functions from the src directory
from src.components import markdown  # Functions for setting background and styling
from src.footer import footer
from src.header import header
from src.logger import log_setup  # Custom logging setup
from src.utils import css_style, get_path, \
    config  # Utility functions for styling, accessing profile data, and image paths


# Define the initial setup function to configure the Streamlit app
def initial_setup():
    global css_style
    # Initialize the logger in the session state if not already present
    if 'logger' not in st.session_state:
        st.session_state.logger = log_setup()  # Set up the logger
        logging.info('Logging setup')  # Log an informational message

    # Load the favicon image from the specified file path
    favicon_path = get_path(config['favicon'])

    # Set the page configuration for the Streamlit app
    st.set_page_config(
        page_title="Rambo Quant Investments",  # Set the page title dynamically
        page_icon=favicon_path,  # Use the favicon image
        layout="centered"  # Use a wide layout for the app
    )

    st.markdown("""
        <head>
            <meta name="description" content="Rambo Quant Investments LLP – Expert investing and trading strategies in the Indian & US markets.">
            <meta name="keywords" content="Rambo Quant, investments, trading, finance, Indian stock market, US stocks, ETFs">
            <meta name="author" content="Rambo Quant Investments LLP">
            <meta property="og:title" content="Rambo Quant Investments – Invest. Grow. Compound.">
            <meta property="og:description" content="Expert investing and trading strategies in the Indian & US markets.">
            <meta property="og:type" content="website">
            <meta property="og:url" content="https://ramboq.com">
    		<meta name="google-site-verification" content="google1530c83c859eefaa.html" />
        </head>
    """, unsafe_allow_html=True)

    # Set the background image for the page
    bin_str = get_image_bin_file('nav_image.png')
    css_style = css_style.replace('nav_image', bin_str)
    bin_str = get_image_bin_file('body_image.png')
    css_style = css_style.replace('body_image', bin_str)

    # Apply CSS styling to the page content
    markdown(css_style, css=True)


def initialize_app_state():
    # Initialize session state
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if "first_time" not in st.session_state:
        st.session_state.first_time = True
        st.session_state.active_nav = config['default_nav_label']


# Main function to execute the initial setup and generate different sections of the profile page
if __name__ == '__main__':
    initial_setup()  # Call the setup function to configure the app

    initialize_app_state()

    nav_container = st.container(key="navbar-container")
    body_container = st.container(key="body-container")
    footer_container = st.container(key='footer-container')

    header(nav_container)
    body(body_container)
    footer(footer_container)
