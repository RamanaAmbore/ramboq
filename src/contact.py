import random
import re

import streamlit as st
from src.helpers.utils import ramboq_config, validate_email, validate_phone, validate_captcha
from src.helpers.utils import isd_codes, send_email  # YAML-loaded ISD codes


def contact(body_container):
    with body_container:
        with st.container(key="contact-container"):
            st.write(ramboq_config["contact"])

            # --- Simple Captcha Question ---
            if "captcha_num1" not in st.session_state:
                st.session_state.captcha_num1 = random.randint(1, 9)
                st.session_state.captcha_num2 = random.randint(1, 9)

            with st.form("contact_form", clear_on_submit=False):  # Don't clear on error
                name = st.text_input("Full Name *", key="name", max_chars=100)
                email = st.text_input("Email Address *", key="email")
                phone_country = st.selectbox("Country Code", isd_codes, key="phone_country")
                phone_number = st.text_input("Phone Number", key="phone_number")
                subject = st.text_input("Subject *", key="subject", max_chars=150)
                query = st.text_area("Your Query *", key="query", height=150)

                # --- Captcha field ---
                captcha_answer = st.text_input(
                    f"Solve to verify: {st.session_state.captcha_num1} + {st.session_state.captcha_num2} = ?",
                    key="captcha"
                )

                col1, col2, _ = st.columns([1, 1, 2], vertical_alignment="center")
                submit = col1.form_submit_button("Submit")

                if submit:
                    # --- Validations ---
                    if not name.strip():
                        st.error("⚠️ Full Name is required.")
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
                        captcha_answer.strip(),
                        st.session_state.captcha_num1,
                        st.session_state.captcha_num2
                    )
                    if not ok:
                        st.error(msg)
                        # regenerate new captcha
                        st.session_state.captcha_num1 = random.randint(1, 9)
                        st.session_state.captcha_num2 = random.randint(1, 9)
                        return

                    # --- Send email ---
                    with st.spinner("📨 Sending your message..."):
                        status, msg = send_email(name, email, query, full_phone, subject, test=False)

                    email_status(status, msg)

                    # regenerate captcha for next attempt
                    st.session_state.captcha_num1 = random.randint(1, 9)
                    st.session_state.captcha_num2 = random.randint(1, 9)


@st.dialog("📨 Email Status")
def email_status(success: bool, msg: str):
    if success:
        st.success("✅ Your message has been sent successfully!")
    else:
        st.error(f"❌ Failed to send your message. {msg}")

    if st.button("Close"):
        st.rerun()