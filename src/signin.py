from datetime import date

import streamlit as st

from src.components import render_form
from src.constants import email_reg_tmpl, email_reset_tmpl
from src.helpers.mail_utils import send_contact_email
from src.utils_streamlit import show_status_dialog


@st.fragment
def user_setup():
    with st.container(key="body-container"):
        with st.container(key='contact-container'):
            # Menu to switch between forms
            menu = st.radio("Choose option:", ["Sign In", "Sign Up", "Reset Password"], horizontal=True)

            # Delegate to the corresponding form function
            if menu == "Sign In":
                signin_form()
            elif menu == "Sign Up":
                signup_form()
            elif menu == "Reset Password":
                reset_form()


def signup_form():
    st.subheader("Create Account")
    fields = ['email_id', 'password', 'confirm_password', 'captcha_answer']
    names = ['Email', 'Password', 'Confirm Password', 'Answer']
    must = [True] * 4

    v_xref, msg = render_form(fields, names, must, form='signup')
    if not v_xref:
        if msg: st.error(msg)
        return

    if v_xref['password'] != v_xref['confirm_password']:
        st.error("❌ Passwords don't match")
        return

    with st.spinner("📝 Creating the account..."):
        status, msg = True, "nop"
        if not status:
            st.error(msg)
            return

    with st.spinner("📨 Sending acknowledgement email..."):
        v_xref['subject'] = f"Registration Acknowledgement: Your registration in RamboQ on {date.today()}"
        html_body = email_reg_tmpl.format(**v_xref)

        status, msg = send_contact_email("", v_xref['email_id'], v_xref['subject'], html_body)

    show_status_dialog(status, msg)


def signin_form():
    st.subheader("Sign In")
    fields = ['email_id', 'account', 'password', 'captcha_answer']
    names = ['Email ', 'Account', 'Password', 'Answer']
    must = [False, False, True, True]  # only password & captcha required
    labels = ['Email (you can leave it blank if you use Account)',
              'Account (you can leave it blank if you use Email)', 'Password *',
              'Answer *']

    v_xref, msg = render_form(fields, names, must, labels, form='signin')

    if not v_xref:
        if msg: st.error(msg)
        return

    with st.spinner("➡️ Processing Sign in..."):
        status, msg = True, "nop"
        if not status:
            st.error(msg)
            return

    show_status_dialog(True, "➡️ Signed in successfully")


def reset_form():
    st.subheader("Reset Password")
    fields = ['email_id', 'account', 'old_password', 'new_password', 'confirm_password', 'captcha_answer']
    names = ['Email', 'Account', 'Current Password', 'New Password', 'Confirm New Password', 'Answer']
    l_xref = ['Email *', 'Account *', 'Current Password *', 'New Password *', 'Confirm New Password *', 'Answer *']
    must = [False, False, True, True, True, True]

    v_xref, msg = render_form(fields, names, must, l_xref, form='reset')
    if not v_xref:
        if msg: st.error(msg)
        return

    with st.spinner("Resetting the account password..."):
        status, msg = True, "nop"
        if not status:
            st.error(msg)
            return

    with (st.spinner("📨 Sending confirmation email...")):
        v_xref['subject'] = \
            f"Password Reset: Your password reset on RamboQ for {v_xref['email_id']} {v_xref['account_no']}on {date.today()}"
        html_body = email_reset_tmpl.format(**v_xref)
        status, msg = send_contact_email('', v_xref['email_id'], v_xref['subject'], html_body)
    show_status_dialog(status, msg)
