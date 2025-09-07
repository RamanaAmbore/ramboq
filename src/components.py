import streamlit as st

from src.helpers.utils import ramboq_config, constants, get_image_bin_file as get_image_file, isd_codes, validate_email, \
    validate_phone, validate_captcha, validate_pin
from src.utils_streamlit import reset_form_state_vars


# Function to set a PNG image as the page background
def set_png_as_page_bg(png_file, icon=False):
    bin_str = get_image_file(png_file)  # Convert image file to binary string
    page_bg_img = f'''
    <style>
        .appview-container {{
            background-image: url("{bin_str}");
        background-size: 100% 100%;
        }}
    </style>
    '''
    st.markdown(page_bg_img, unsafe_allow_html=True)  # Apply custom styles using Markdown
    return


# Wrapper function for streamlit's container element to support function calls within it
def container(*args, **kwargs):
    function = args[0]  # The function to be executed within the container
    args = args[1:]
    if 'key' in kwargs:
        key = kwargs.pop('key')  # Unique key for container
        container = st.container(key=key)
        with container:
            return function(*args, **kwargs)  # Return function inside container

    return function(*args, **kwargs)  # Return function without container


# # Function to render Markdown text with optional styling
# def markdown(text, style_tag=True):
#     if style_tag:
#         text = f'<style>{text}</style>'  # Wrap text in <style> tag for styling
#     st.markdown(f'{text}', unsafe_allow_html=True)  # Render styled Markdown

# Wrapper function for streamlit's container element to support function calls within it
def markdown(html_block, **kwargs):
    style = ""
    if 'css' in kwargs and kwargs['css']:
        return st.markdown(f"<style>{html_block}</style>", unsafe_allow_html=True)
    if 'style' in kwargs:
        style = kwargs.pop('style')  # Unique key for container
    if 'class_name' in kwargs:
        class_name = kwargs.pop('class_name')
        style = f"class='{class_name}'"
    if 'key' in kwargs:
        id = kwargs.pop('key')
        style = f"{style} id='{id}'"

    tag = kwargs.pop('tag') if 'tag' in kwargs else 'div'

    html_block = f"<{tag} {style}> {html_block}</{tag}>"

    return st.markdown(html_block, unsafe_allow_html=True, **kwargs)  # Return function without container


# Function to display a section heading with an optional icon and styling
def write_section_heading(text):
    icon = ramboq_config["section_icons"]  # Get icon from config based on section name
    st.subheader(f':{icon[text]}: {text.title()}', anchor=text.title(), divider='rainbow')  # Display section heading


# Function to display a subheading with text
def write_subheading(heading, text, key=None):
    st.write(f"**{heading.title()}:** {text}")  # Display heading and text


# Function to display an icon with text and a link, with optional custom HTML tag
def disp_icon_text(icon=None, text=None, link=None, tag=""):
    icon = get_image_file(icon)  # Get the binary string of the icon image
    text = "" if text is None else text
    if tag == "":
        tag = f"<img src='{icon}' class='href_icon'>{text}"  # Format icon with text
    else:
        tag = f"<{tag}><img src='{icon}' class='href_icon'>{text}</{tag}>"  # Use custom HTML tag for text

    if link is None:
        markdown_text = f"""
                <div class='icon_href_text_div'>
                    <span class='href_link'> 
                        {tag}
                    </span>
                </div>
                """
    else:
        markdown_text = f"""
                    <div class='icon_href_text_div'>
                        <span> 
                            <a href="{link}" 
                            class='href_link'><span class='href_text'>{tag}</a>
                        </span>
                    </div>"""

    st.markdown(markdown_text, unsafe_allow_html=True)


# Function to create a horizontal rule (line)
def create_ruler():
    st.markdown('---', unsafe_allow_html=True)  # Render a horizontal rule using Markdown


# Function to create a horizontal rule (line)
def create_ruler_white():
    st.markdown("<hr style='border: 1px solid white;'>",
                unsafe_allow_html=True)  # Render a horizontal rule using Markdown


# Function to display profile information in a container based on the name
def write_container(name):
    profile_section = constants[name]  # Get profile section for the given name
    for key, vals in profile_section.items():
        disp_icon_text(vals['icon'], vals['long label'], vals['link'])  # Display icon and text for each profile item


# Function to display profile information in columns
def write_columns(column_list, name):
    profile_section = constants[name]  # Get profile section for the given name
    profile_keys = list(profile_section.keys())  # List of profile keys
    size = len(profile_keys) - 1  # Total number of profile items
    profile_vals = list(profile_section.values())  # List of profile values

    for idx, col in enumerate(column_list):  # Loop through the columns to display content
        if idx > size: return  # Stop if the column index exceeds the number of profile items
        vals = profile_vals[idx]  # Get the profile values for the current index
        label = vals['label'] if 'label' in vals else profile_keys[idx]  # Use 'label' if it exists
        with col:
            disp_icon_text(vals['icon'], label, vals['link'])  # Display the profile icon, label, and link


def render_form(fields, names, must, labels=None, disabled=None, form='contact'):
    """
    Render a generic form based on fields, names, and must (required).
    Returns dict of field values if submitted, else None.
    """

    # xref dictionaries
    xref = dict(zip(fields, names))
    m_xref = dict(zip(fields, must))
    if disabled is None:
        disabled = [False] * len(fields)
    d_xref = dict(zip(fields, disabled))

    if labels is not None:
        l_xref = dict(zip(fields, labels))
    else:
        l_xref = {key: (f'{xref[key]} *' if m_xref[key] else xref[key]) for key in fields}

    if 'captcha_answer' in fields:
        reset_form_state_vars(fields, form)

    with (((((((((st.form("ramboq_form", clear_on_submit=False)))))))))):  # Don't clear on error
        for fld in fields:
            if 'ph_country' in fld:
                st.selectbox(l_xref[fld], isd_codes, key=fld, disabled=d_xref[fld])
            elif 'password' in fld:
                st.text_input(l_xref[fld], type='password', key=fld, disabled=d_xref[fld])
            elif 'dob' in fld:
                st.date_input(l_xref[fld], key=fld)
            elif 'query' in fld:
                st.text_area(l_xref[fld], key=fld, height=150, disabled=d_xref[fld])
            elif 'same' in fld:
                    st.checkbox(l_xref[fld],  key=fld, disabled=d_xref[fld])
            elif not fld.startswith('captcha'):
                st.text_input(l_xref[fld], key=fld, disabled=d_xref[fld])
            # --- Captcha field ---
            elif fld.startswith('captcha'):
                captcha_answer = st.text_input("Answer", key='captcha_answer', disabled=d_xref[fld])
                st.write(
                    f"Solve to verify: {st.session_state['captcha_num1']} + {st.session_state['captcha_num2']} = ?")

        col, _ = st.columns([1, 3], vertical_alignment="center")
        submit = col.form_submit_button("Submit")

        if submit:
            v_xref = {key: st.session_state[key].strip() for key in fields if key not in ['same', 'dob']}

            for key in fields:
                if m_xref[key] and not v_xref[key]:
                    return False, f"⚠️ {xref[key]} is required"

                elif 'email_id' in fld and v_xref['email_id'] and not validate_email(v_xref['email_id']):
                    return False, "❌ Invalid email format."

                elif 'ph_num' in fld:
                    if v_xref['ph_num']:
                        ok, msg, st.session_state.full_phone = validate_phone(v_xref['ph_country'], v_xref['ph_num'])
                        v_xref['ph_num'] = st.session_state.full_phone
                        if not ok:
                            # st.error(msg)
                            return False, msg
                    else:
                        st.session_state.full_phone = ""

                elif 'pin' in fld:
                    ok, msg, pin = validate_pin(v_xref[fld])
                    if not ok:
                        return False, msg
                    else:
                        st.session_state[fld] = pin
                elif 'same' in fld and v_xref[fld]:
                    print('same here')
                    st.session_state['nom_address_line1']=st.session_state['address_line1']
                    st.session_state['nom_address_line2']=st.session_state['address_line2']
                    st.session_state['nom_landmark']=st.session_state['landmark']
                    st.session_state['nom_city']=st.session_state['city']
                    st.session_state['nom_state']=st.session_state['state']
                    st.session_state['nom_pin_code']=st.session_state['pin_code']
                    st.session_state['nom_country']=st.session_state['country']
                    st.session_state['nom_ph_country1']=st.session_state['ph_country1']
                    st.session_state['nom_ph_num1']=st.session_state['ph_num1']
                    st.session_state['nom_ph_country2']=st.session_state['ph_country2']
                    st.session_state['nom_ph_num2']=st.session_state['ph_num2']
                    st.session_state['nom_email_id1']=st.session_state['email_id']
                    st.session_state['nom_email_id2'] = st.session_state['email_id1']
                    st.session_state['same'] = False
                    st.rerun()
                elif 'age' in fld:
                    try:
                        st.session_state[fld] = int(st.session_state[fld])
                    except:
                        return False, "Invalid Age"



            # --- Captcha validation ---
            if 'captcha_answer' in fields:
                ok, msg = validate_captcha(
                    captcha_answer, st.session_state['captcha_result'])
                if not ok:
                    # st.error(msg)
                    return False, msg

            return v_xref, ""

        return False, ""
