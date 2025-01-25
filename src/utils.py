import base64
import functools
import logging
import random
from io import BytesIO

import streamlit
import yaml
from PIL import Image


# Function to get the path of an image file
def get_path(file):
    # Return the appropriate path based on whether the image is a certificate
    if 'http' in file: return file
    type = file.split('.')[1]
    dirs = {'jpg': 'images/',
            'ico': 'images/',
            'png': 'images/',
            'jpeg': 'images/',
            'css': 'style/',
            'pdf': 'resume/',
            'certificate': 'images/certificates/',
            'yaml': 'yaml/'}
    return f"setup/{dirs[type]}/{file}"
    # Custom dictionary class to handle keys with suffix matching


class CustomDict(dict):
    def __getitem__(self, key):
        # Check if any key in the dictionary ends with the specified key
        for k in self.keys():
            if k.endswith(key):
                return super().__getitem__(k)

        return None


# Load profile data from a YAML file
with open(get_path('profile_data.yaml'), 'r', errors='ignore') as file:
    profile = yaml.safe_load(file)  # Load YAML file into a Python dictionary

# Load custom CSS styles for styling the frontend
with open(get_path("style.css"), "r") as css:
    css_style = css.read()  # Read the CSS file into a string

# Read and store a PDF file (resume) in memory for download or display
with open(get_path("resume.pdf"), "rb") as pdf_file:
    pdf_resume = pdf_file.read()

# Load additional configuration data from a YAML file
with open('setup/yaml/config.yaml', 'r') as file:
    config = yaml.safe_load(file)  # Load YAML config file
    colors = config['colors']
    dark_colors = config['dark_colors']
    sidebar_icons = config['sidebar_icons']
    section_icons = config['section_icons']
    freq_color = config['freq_color']


@streamlit.cache_resource
def get_image_bin_file(file):
    """
    Encodes an image file as a Base64 string for embedding in HTML.
    """

    if 'http' in file: return file
    img = Image.open(get_path(file))  # Open the image file
    format = file[-3:].upper()  # Extract the file format (e.g., PNG, JPG)

    # Encode the image into a Base64 string
    buffered = BytesIO()
    img.save(buffered, format=format)
    img_str = base64.b64encode(buffered.getvalue()).decode()
    url = f'data:image/{format.lower()};base64,{img_str}'
    return url


# Debug wrapper to log the start and end of functions
def debug_wrapper(function):
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        logging.debug(f'{function.__name__} started')  # Log function start
        result = function(*args, **kwargs)
        logging.debug(f'{function.__name__} ended')  # Log function end
        return result

    return wrapper



def get_selected_colors(lst, size):
    """
    Select a random subset of colors from a list.
    If the list is smaller than the requested size, repeat elements.
    """
    return random.sample(lst, size) if len(lst) > size else random.choices(lst, size)


@streamlit.cache_resource
def get_config(name):
    """
    Retrieve a section from the config dictionary and return its keys and values.
    """
    section = config[name]
    return list(section.keys()), list(section.values())


@streamlit.cache_resource
def get_profile(name):
    """
    Retrieve a section from the profile dictionary and return its keys and values.
    """
    section = profile[name]
    return list(section.keys()), list(section.values())


@streamlit.cache_resource
def capitalize(text):
    """
    Capitalize text if it doesn't already contain uppercase characters.
    """
    return text if any([x.isupper() for x in text]) else text.title()


@streamlit.cache_resource
def get_labels(name, label='label'):
    """
    Get a list of capitalized labels for a given profile section.
    """
    section = profile[name]
    return [capitalize(vals[label] if label in vals else key) for key, vals in section.items()]


@streamlit.cache_resource
def get_darker_color(hex_color, factor=0.5):
    """
    Darken a given hex color by a specified factor.
    Factor should be between 0 (black) and 1 (original color).
    """
    if not (0 <= factor <= 1):
        raise ValueError("Factor must be between 0 and 1")

    # Convert hex color to RGB
    hex_color = hex_color.lstrip('#')
    r, g, b = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:], 16)

    # Apply the factor to each channel
    r = int(r * factor)
    g = int(g * factor)
    b = int(b * factor)

    # Clamp values between 0 and 255 and return the new hex color
    return f"#{r:02x}{g:02x}{b:02x}"


@streamlit.cache_resource
def get_darker_colors(hex_color_list, factor=0.75):
    """
    Darken a list of hex colors by a specified factor.
    """
    return [get_darker_color(color, factor) for color in hex_color_list]
