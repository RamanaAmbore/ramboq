import re
import re

import streamlit as st
import streamlit as st
from src.utils import config
from src.utils import isd_codes, send_email  # YAML-loaded ISD codes


def contact(body_container):

    with body_container:
        with st.container(key="contact-container"):
            st.write(config["contact"])

            with st.form("contact_form", clear_on_submit=False):  # Don't clear on error
                name = st.text_input("Full Name *", key="name", max_chars=100)
                email = st.text_input("Email Address *", key="email")
                phone_country = st.selectbox("Country Code", isd_codes, key="phone_country")
                phone_number = st.text_input("Phone Number", key="phone_number")
                subject = st.text_input("Subject *", key="subject", max_chars=150)
                query = st.text_area("Your Query *", key="query", height=150)

                col1, col2, _ = st.columns([1, 1, 2], vertical_alignment="center")
                submit = col1.form_submit_button("Submit")

                if submit:
                    # --- Ordered validation ---
                    if not name.strip():
                        st.error("⚠️ Full Name is required.")
                        return
                    if not email.strip():
                        st.error("⚠️ Email Address is required.")
                        return

                    email_pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
                    if not re.match(email_pattern, email.strip()):
                        st.error("❌ Invalid email format.")
                        return

                    if phone_number.strip():
                        country_code = re.sub(r"\D", "", phone_country)  # keep only digits
                        full_phone = f"+{country_code}{phone_number.strip()}"
                        phone_pattern = r"^[0-9+\s()]+$"
                        if not re.match(phone_pattern, full_phone):
                            st.error("❌ Phone number may only contain digits, +, spaces, ( and )")
                            return
                        digits_only = re.sub(r"\D", "", phone_number)
                        if not (7 <= len(digits_only) <= 15):
                            st.error("❌ Phone number must be between 7 and 15 digits")
                            return
                    else:
                        full_phone = ""

                    if not subject.strip():
                        st.error("⚠️ Subject is required.")
                        return
                    if not query.strip():
                        st.error("⚠️ Query is required.")
                        return

                    # --- Send email ---
                    with st.spinner("📨 Sending your message..."):
                        status, msg = send_email(name, email, full_phone, query, subject)

                    if status:
                        st.success("✅ Your message has been sent successfully!")

                        st.rerun()  # 🔄 Restart script to refresh cleared state
                    else:
                        st.error(f"❌ Failed to send your message. {msg}")
                        return
