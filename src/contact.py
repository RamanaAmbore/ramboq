import streamlit as st

from src.helpers.utils import isd_codes  # YAML-loaded ISD codes
from src.helpers.mail_utils import send_contact_email
from src.helpers.utils import ramboq_config, validate_email, validate_phone, validate_captcha
from src.utils_streamlit import show_status_dialog, set_captcha_state


@st.fragment
def contact():
    with st.container(key="body-container"):
        with st.container(key='contact-container'):
            st.write(ramboq_config["contact"])
            lst = ['name', 'email', 'phone_number', 'subject', 'query', 'answer']
            set_captcha_state(lst, 'contact_clear')

            with st.form("contact_form", clear_on_submit=False):  # Don't clear on error
                name = st.text_input("Full Name *", key="name", max_chars=100)
                email = st.text_input("Email Address *", key="email")
                phone_country = st.selectbox("Country Code", isd_codes, key="phone_country")
                phone_number = st.text_input("Phone Number", key="phone_number")
                subject = st.text_input("Subject *", key="subject", max_chars=150)
                query = st.text_area("Your Query *", key="query", height=150)

                # --- Captcha field ---
                captcha_answer = st.text_input("Answer", key='answer')
                st.write(
                    f"Solve to verify: {st.session_state['captcha_num1']} + {st.session_state['captcha_num2']} = ?")
                print(captcha_answer)

                col1, col2, _ = st.columns([1, 1, 2], vertical_alignment="center")
                submit = col1.form_submit_button("Submit")

                if submit:
                    # --- Validations ---
                    if not name.strip():
                        st.error("⚠️ Name is required.")
                        return
                    if not email.strip():
                        st.error("⚠️ Email Address is required.")
                        return

                    if not validate_email(email.strip()):
                        st.error("❌ Invalid email format.")
                        return

                    full_phone = ""
                    if phone_number.strip():
                        ok, msg, full_phone = validate_phone(phone_country, phone_number.strip())
                        if not ok:
                            st.error(msg)
                            return

                    if not subject.strip():
                        st.error("⚠️ Subject is required.")
                        return

                    if not query.strip():
                        st.error("⚠️ Query is required.")
                        return

                    # --- Captcha validation ---
                    ok, msg = validate_captcha(
                        captcha_answer.strip(), st.session_state['captcha_result'])
                    if not ok:
                        st.error(msg)
                        return

                    # --- Send email ---
                    with st.spinner("📨 Sending your message..."):
                        status, msg = send_contact_email({'name', 'email', 'query', 'full_phone', 'subject'})

                    show_status_dialog(status, msg)
