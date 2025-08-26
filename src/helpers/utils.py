import base64
import functools
import logging
import shutil
import smtplib
from collections import defaultdict
from datetime import date
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO
from pathlib import Path

import pandas as pd
import pyotp
import yaml
from PIL import Image


def get_path(file):
    # Return the appropriate path based on whether the image is a certificate
    if 'http' in file: return file
    typ = file.split('.')[1]
    dirs = {'jpg': 'images/',
            'ico': 'images/',
            'png': 'images/',
            'jpeg': 'images/',
            'css': 'style/',
            'pdf': 'resume/',
            'certificate': 'images/certificates/',
            'yaml': 'yaml/'}
    return f"setup/{dirs[typ]}/{file}"
    # Custom dictionary class to handle keys with suffix matching


class CustomDict(dict):
    def __getitem__(self, key):
        # Check if any key in the dictionary ends with the specified key
        for k in self.keys():
            if k.endswith(key):
                return super().__getitem__(k)

        return None


# Load profile data from a YAML file
with open(get_path('ramboq_constants.yaml'), 'r', errors='ignore', encoding='utf-8') as file:
    constants = yaml.safe_load(file)  # Load YAML file into a Python dictionary

# Load custom CSS styles for styling the frontend
with open(get_path("style.css"), "r", encoding='utf-8', errors='ignore') as css:
    css_style = css.read()  # Read the CSS file into a string

# Load additional configuration data from a YAML file
with open('setup/yaml/ramboq_config.yaml', 'r', encoding='utf-8', errors='ignore') as file:
    ramboq_config = yaml.safe_load(file)  # Load YAML config file

# Load additional configuration data from a YAML file
with open('setup/yaml/secrets.yaml', 'r', encoding='utf-8', errors='ignore') as file:
    secrets = yaml.safe_load(file)  # Load YAML config file

# Load configuration from YAML file
with open('setup/yaml/ramboq_deploy.yaml', 'r', encoding='utf-8', errors='ignore') as file:
    ramboq_deploy = yaml.safe_load(file)

# Load additional configuration data from a YAML file
with open('setup/yaml/config.yaml', 'r', encoding='utf-8', errors='ignore') as file:
    config = yaml.safe_load(file)  # Load YAML config file

isd_codes = [f"{item['country']} ({item['code']})" for item in constants['isd_codes']]


def get_image_bin_file(file):
    """
    Encodes an image file as a Base64 string for embedding in HTML.
    """

    if 'http' in file: return file
    img = Image.open(get_path(file))  # Open the image file
    frmt = file[-3:].upper()  # Extract the file frmt (e.g., PNG, JPG)

    # Encode the image into a Base64 string
    buffered = BytesIO()
    img.save(buffered, format=frmt)
    img_str = base64.b64encode(buffered.getvalue()).decode()
    url = f'data:image/{frmt.lower()};base64,{img_str}'
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


def capitalize(text):
    """
    Capitalize text if it doesn't already contain uppercase characters.
    """
    return text if isinstance(text, (int, float)) or any([x.isupper() for x in text]) else text.title()


def word_width(text, cap_factor=0.28, small_factor=0.17):
    caps = 0
    smalls = 0
    for letter in text:
        if letter.isupper():
            caps += 1
        else:
            smalls += 1
    return caps * cap_factor + smalls * small_factor


def send_email(name, to_email, query, phone="", subject="", test=False):
    """
    Email a single recipient, CC to the smtp_user.
    - to_email: str (single email address)
    """

    smtp_server = secrets['smtp_server']
    smtp_port = secrets['smtp_port']
    smtp_user = secrets['smtp_user']
    smtp_pass = secrets['smtp_pass']

    # --- Subject ---
    subject = f"New Contact Form Submission from {name}" if subject == "" else f"{subject} from {name}"
    subject = f"{subject} on {date.today()}"

    # --- Body ---
    body = f"""
    <html>
      <body>
        <p>Dear {name},</p>
        <p>
          Thank you for reaching out to us. We have successfully received your message, 
          and our team is currently reviewing the details.<br>
          We will get back to you at the earliest possible time.
        </p>

        <p><b>Details you submitted:</b></p>
        <ul>
          <li><b>Name:</b> {name}</li>
          <li><b>Phone:</b> {phone}</li>
          <li><b>Email:</b> {to_email}</li>
          <li><b>Subject:</b> {subject}</li>
          <li><b>Message/Query:</b> {query}</li>
        </ul>

        <p>Best regards,<br>[Rambo team]</p>
      </body>
    </html>
    """

    # --- Build message ---
    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = to_email.strip()
    msg["Cc"] = smtp_user
    msg["Subject"] = f'Acknowledgement: {subject}'
    msg.attach(MIMEText(body, "html"))

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


def generate_totp(totp_key):
    """Generate a valid TOTP using the secret key."""
    return pyotp.TOTP(totp_key).now()


def to_decimal(value, precision="0.01"):
    """Convert float to Decimal with specified precision."""
    return Decimal(value).quantize(Decimal(precision), rounding=ROUND_DOWN)


def delete_folder_contents(folder_path):
    """Deletes all files and subdirectories inside the specified folder."""
    folder = Path(folder_path)

    if not folder.exists() or not folder.is_dir():
        print(f"Folder '{folder_path}' does not exist or is not a directory.")
        return False

    success = True
    for item in folder.iterdir():
        try:
            if item.is_file() or item.is_symlink():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        except Exception as e:
            print(f"Failed to delete {item}: {e}")
            success = False
    return success


def read_file_content(file_path, file_extension):
    """Reads the content of a file based on its extension."""
    try:
        if file_extension == "txt":
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        elif file_extension == "csv":
            return pd.read_csv(file_path)  # Convert DataFrame to string
        elif file_extension == "xlsx":
            return pd.read_excel(file_path)  # Convert DataFrame to string
        else:
            print(f"Unsupported file format: {file_extension}")
            return ""
    except Exception as e:
        print(f"Error reading file {file_path}: {e}")
        return ""


def parse_value(value: str, target_type: type = None):
    """Converts a string into its appropriate data type or a specified type."""

    if value is None: return None
    value = value.strip()
    if value == 'None': return None

    if value == "":
        return ""  # Return empty string for empty input

    if target_type:
        try:
            if target_type is bool:
                return value.lower() == "true"
            return target_type(value)
        except (ValueError, TypeError):
            raise ValueError(f"Cannot convert '{value}' to {target_type.__name__}")

    if value.lower() in ("true", "false"):
        return value.lower() == "true"

    if value.isdigit() or (value[0] in "+-" and value[1:].isdigit()):
        return int(value)

    try:
        return float(value)
    except ValueError:
        return value


def create_instr_symbol_xref(data, xref, reverse_key=None, use_type=set):
    symbol_id_xref = reverse_dict(data, reverse_key, use_type)
    instr_id_xref = {}
    for key, val in symbol_id_xref.items():
        instr_id_xref[xref[key]['instrument_token']] = val
    return symbol_id_xref, instr_id_xref


def reverse_dict(data, reverse_key=None, use_type=set):
    if use_type is None:
        multi_set_dict = dict()
    else:
        multi_set_dict = defaultdict(use_type)

    for key, val in data.items():
        temp_key = val[reverse_key]
        if use_type is None:
            multi_set_dict[temp_key] = key
        else:
            multi_set_dict[temp_key].add(key)

    if use_type is None:
        return multi_set_dict
    else:
        return dict(multi_set_dict)


def rec_to_dict(record):
    return {k: v for k, v in record.__dict__.items() if not k.startswith('_')} if record else {}


def get_closing_date():
    now = datetime.now()
    today_8am = now.replace(hour=8, minute=0, second=0, microsecond=0)

    if now >= today_8am:
        dt = now.date()
    else:
        dt = (now - timedelta(days=1)).date()
    return dt


if __name__ == "__main__":
    # Test run
    name = "Rambo"
    recipients = "ramboquant@gmail.com"
    phone = "9876543210"
    query = "Testing multiple recipient email functionality."

    success, msg = send_email(name, recipients, query, test=True)
    if success:
        print("✅ Email sent successfully!")
    else:
        print("❌ Failed to send email:", msg)
