import base64
import re
import shutil
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from io import BytesIO
from pathlib import Path

import pandas as pd
import pyotp
import yaml
from PIL import Image
from babel.numbers import format_decimal

from src.helpers.date_time_utils import timestamp_indian


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
    nav_labels = ramboq_config['nav_labels']
    default_nav_label = ramboq_config['default_nav_label']
    signin_label = "signin"
    signout_label = "signout"
    signin_label_val = "Sign in/Sign up"
    signout_label_val = "Sign out"
    nav_plus_signin = ramboq_config['nav_labels'] + [signin_label]
    nav_plus_signin_out = ramboq_config['nav_labels'] + [signin_label, signout_label]
    logo = get_path(ramboq_config['logo'])

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





def round_down_to_interval(dt: datetime, interval_minutes: int) -> datetime:
    total_minutes = dt.hour * 60 + dt.minute
    rounded_total_minutes = (total_minutes // interval_minutes) * interval_minutes

    rounded_hour = rounded_total_minutes // 60
    rounded_minute = rounded_total_minutes % 60

    return dt.replace(hour=rounded_hour % 24, minute=rounded_minute, second=0, microsecond=0)


def get_cycle_date(hours=8, mins=0):
    now = timestamp_indian()
    today_cutoff = now.replace(hour=hours, minute=mins, second=0, microsecond=0)

    if now >= today_cutoff:
        dt = now.date()
    else:
        dt = (now - timedelta(days=1)).date()
    return dt


def get_nearest_time(from_hour: int = 9, from_min: int = 0, to_hour: int = 23, to_min: int = 30,
                     interval: int = 10) -> str:
    now = timestamp_indian()
    from_time = now.replace(hour=from_hour, minute=from_min, second=0, microsecond=0)
    to_time = now.replace(hour=to_hour, minute=to_min, second=0, microsecond=0)

    # Handle time window crossing midnight

    in_window = from_time <= now <= to_time


    if in_window:
        rounded_time = round_down_to_interval(now, interval)
        return rounded_time.strftime("%d-%b-%y %H:%M")
    else:
        # Assume get_cycle_date returns a date object
        cycle_date = get_cycle_date(hours=9, mins=0)  # e.g., datetime.date(2025, 9, 7)

        # Combine with fixed time (23:30)
        fixed_datetime = datetime.combine(cycle_date, datetime.min.time()).replace(hour=23, minute=30)

        # Format as desired
        return fixed_datetime.strftime("%d-%b-%y %H:%M")


def mask_column(col):
    return col.astype(str).str.replace(r'\d', '#', regex=True)


def add_comma_to_df_numbers(df):
    # Format numeric cols with Indian commas
    num_cols = df.select_dtypes(include=["number"]).columns.tolist()
    for col in num_cols:
        df[col] = df[col].apply(add_comma_to_number)
    return df


def add_comma_to_number(x):
    if pd.isna(x):
        return ""
    try:
        num = float(x)
        if abs(num) >= 1000:
            # No decimals for numbers >= 1000
            return format_decimal(num, locale="en_IN", format="#,##,##0")
        else:
            # Max 2 decimal places
            return format_decimal(num, locale="en_IN", format="#,##0.##")
    except Exception:
        return x


def validate_email(email: str) -> bool:
    """Check if email has a valid format."""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(pattern, email) is not None


def validate_password_standard(password: str) -> tuple[bool, str]:
    """
    Validate password if not in production.
    Returns:
        (bool, str): (is_valid, message)
    """
    if not ramboq_deploy['prod'] and not ramboq_deploy['enforce_password_standard']:
        return True, "Validation skipped in production mode."

    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"[0-9]", password):
        return False, "Password must contain at least one digit."
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "Password must contain at least one special character."

    return True, "Password is valid."


def validate_captcha(answer, result):
    try:
        if float(answer) == result:
            return True, "Captcha validated successfully."
        else:
            return False, "Captcha answer is incorrect."
    except ValueError:
        return False, "Please enter a numeric answer for the captcha."


def validate_phone(country_code: str, phone_number: str):
    # Keep only digits in country code

    if not country_code:
        return False, "❌ Phone country code is not selected", None

    phone_pattern = r"^[0-9+\s()]+$"
    if not re.match(phone_pattern, phone_number):
        return False, "❌ Phone number may only contain digits, +, spaces, ( and )", None

    digits_only = re.sub(r"\D", "", phone_number)
    if not (7 <= len(digits_only) <= 15):
        return False, "❌ Phone number must be between 7 and 15 digits", None

    return True, "", digits_only





def validate_pin(pin: str):
    # Remove all non-numeric characters
    numeric_pin = re.sub(r"\D", "", pin)

    # Validate length (assuming valid lengths are 5 or 6 digits)
    if len(numeric_pin) in (5, 6):
        return True, "Valid PIN code.", numeric_pin

    else:
        return False, "Invalid PIN code length. Expected 5 or 6 digits.", None
