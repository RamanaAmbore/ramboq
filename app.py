import streamlit as st

from src.about import about
from src.contact import contact
from src.faq import faq
from src.market import market
from src.performance import performance
from src.post import post
from src.signin import signin

# Patch before anything else touches st.cache
if hasattr(st, "cache") and hasattr(st, "cache_data"):
    st.cache = st.cache_data

from streamlit_cookies_manager import EncryptedCookieManager

# Import custom components and functions from the src directory
from src.components import markdown  # Functions for setting background and styling
from src.footer import footer
from src.header import create_navbar
from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import get_path, css_style, \
    ramboq_config, nav_plus_signin, \
    default_nav_label, nav_plus_signin_out, \
    capitalize, signin_label, signout_label, \
    signin_label_val, signout_label_val, \
    secrets  # Utility functions for styling, accessing profile data, and image paths
from src.utils_streamlit import get_image_bin_file

logger = get_logger(__name__)

# Monkey patch st.cache → st.cache_data if any package still uses it
if hasattr(st, "cache") and hasattr(st, "cache_data"):
    st.cache = st.cache_data

# Create cookie manager
cookies = EncryptedCookieManager(
    prefix="ramboq_",  # prefix for your app cookies
    password=secrets['cookie_secret'],  # should be kept secret
)

if not cookies.ready():
    st.stop()  # Wait until cookies are available


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

    create_navbar()

    # Create a mapping from nav labels to functions
    page_functions = {
        "signin": signin,
        "about": about,
        "market": market,
        "performance": performance,
        "faq": faq,
        "post": post,
        "contact": contact,
    }

    page_functions[st.session_state.active_nav]()

    footer()
