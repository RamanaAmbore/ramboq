import base64
import functools
import logging
import random
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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
with open(get_path('constants.yaml'), 'r', errors='ignore', encoding='utf-8') as file:
    constants = yaml.safe_load(file)  # Load YAML file into a Python dictionary

# Load custom CSS styles for styling the frontend
with open(get_path("style.css"), "r", encoding='utf-8', errors='ignore') as css:
    css_style = css.read()  # Read the CSS file into a string

# Load additional configuration data from a YAML file
with open('setup/yaml/config.yaml', 'r', encoding='utf-8', errors='ignore') as file:
    config = yaml.safe_load(file)  # Load YAML config file

# Load additional configuration data from a YAML file
with open('setup/yaml/secrets.yaml', 'r', encoding='utf-8', errors='ignore') as file:
    secrets = yaml.safe_load(file)  # Load YAML config file

isd_codes = [f"{item['country']} ({item['code']})" for item in config['isd_codes']]


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
    section = constants[name]
    return list(section.keys()), list(section.values())


@streamlit.cache_resource
def capitalize(text):
    """
    Capitalize text if it doesn't already contain uppercase characters.
    """
    return text if isinstance(text, (int, float)) or any([x.isupper() for x in text]) else text.title()


@streamlit.cache_resource
def get_labels(name, label='label'):
    """
    Get a list of capitalized labels for a given profile section.
    """
    section = constants[name]
    return [capitalize(vals[label] if label in vals else key) for key, vals in section.items()]


@streamlit.cache_resource
def get_darker_color(hex_color, factor=0.75):
    """
    Darken a given hex color by a specified factor.
    Factor should be between 0 (black) and 1 (original color).
    """
    if not (0 <= factor):
        raise ValueError("Factor must be between 0 and 1")

    # Convert hex color to RGB
    hex_color = hex_color.lstrip('#')
    r, g, b = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:], 16)

    # Apply the factor to each channel
    r = int(r * factor)
    if r > 255: r = 255
    g = int(g * factor)
    if g > 255: g = 255
    b = int(b * factor)
    if b > 255: b = 255

    # Clamp values between 0 and 255 and return the new hex color
    return f"#{r:02x}{g:02x}{b:02x}"


@streamlit.cache_resource
def get_darker_colors(hex_color_list, factor=0.75):
    """
    Darken a list of hex colors by a specified factor.
    """
    return [get_darker_color(color, factor) for color in hex_color_list]


@streamlit.cache_resource
def word_width(text, cap_factor=0.28, small_factor=0.17):
    caps = 0
    smalls = 0
    for letter in text:
        if letter.isupper():
            caps += 1
        else:
            smalls += 1
    return caps * cap_factor + smalls * small_factor


@streamlit.cache_resource
def hover_split(text, size=40):
    lines = []
    line = ''
    for word in text.split():
        if word.strip() != '':
            if len(test_line := f'{line} {word}') < size:
                line = test_line
            else:
                lines.append(line)
                line = word
    lines.append(line)

    lines = '<br>'.join(lines)
    return lines


def send_email(name, to_email, query, phone="", subject="", test=False):
    """
    Send email to a single recipient, CC to the smtp_user.
    - to_email: str (single email address)
    """

    smtp_server = secrets['smtp_server']
    smtp_port = secrets['smtp_port']
    smtp_user = secrets['smtp_user']
    smtp_pass = secrets['smtp_pass']

    # --- Subject ---
    subject = f"New Contact Form Submission from {name}" if subject == "" else f"{subject} from {name}"
    subject = f"Acknowledgement: {subject} on {date.today()}"

    # --- Body ---
    body = f"""
    Thank you very much for contacting us. Here is contact form you submitted. We will get back to you as soon as we can. 
    Name: {name}
    Phone: {phone}
    Email: {to_email}
    Subject: {subject}
    Query:
    {query}
    """

    # --- Build message ---
    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = to_email.strip()
    msg["Cc"] = smtp_user
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    # Final recipient list for SMTP
    recipients = to_email.strip()

    try:
        if test:
            print(msg.as_string())
            return True, "Test mode only"
        else:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, recipients, msg.as_string())  # ✅ send to both To & CC
            return True, ''
    except Exception as e:
        err_msg = f"Email send error: {e}"
        return False, err_msg


if __name__ == "__main__":
    # Test run
    name = "Rambo"
    recipients = "ramboquant@gmail.com"
    phone = "9876543210"
    query = "Testing multiple recipient email functionality."

    success, msg = send_email(name, recipients, query, phone, subject, test=True)
    if success:
        print("✅ Email sent successfully!")
    else:
        print("❌ Failed to send email:", msg)
