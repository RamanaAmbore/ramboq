from datetime import date

import streamlit as st

from src.components import render_form
from src.constants import email_ack_tmpl
from src.helpers.mail_utils import send_contact_email
from src.helpers.utils import ramboq_config
from src.utils_streamlit import show_status_dialog


@st.fragment
def contact():
    with st.container(key="body-container"):
        with st.container(key='contact-container'):
            st.write(ramboq_config["contact"])
            # field list
            fields = ['name', 'email_id', 'ph_country', 'ph_num', 'subject', 'query', 'captcha_answer']
            names = ['Name', 'Email Address', 'Phone Country Code', 'Phone Number', 'Subject', 'Your query', 'Answer']
            must = [True, True, False, False, True, True, False]

            v_xref, msg = render_form(fields, names, must)
            if not v_xref:
                if msg:
                    st.error(msg)
                return


            v_xref['subject'] = f"Acknowledgement: {v_xref['subject']} on {date.today()}"

            # Usage:
            html_body = email_ack_tmpl.format(**v_xref)

            # --- Send email ---
            with st.spinner("📨 Sending your message..."):
                status, msg = send_contact_email(v_xref['name'], v_xref['email_id'], v_xref['subject'],
                                                 html_body)

            show_status_dialog(status, msg)
