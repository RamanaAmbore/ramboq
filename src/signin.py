import streamlit as st

from src.constants import email_reg_tmpl, email_reset_tmpl
from src.helpers.mail_utils import send_contact_email
from src.helpers.utils import validate_captcha, validate_password, validate_email
from src.utils_streamlit import set_captcha_state, show_status_dialog


@st.fragment
def signin():
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
                reset_password_form()


def signin_form():
    st.subheader("Sign In")
    lst = ['signin_email', 'signin_account', 'signin_password', 'signin_answer']
    set_captcha_state(lst, 'signin_clear')

    with st.form("signin_form", clear_on_submit=False):
        email_id = st.text_input("Email (leave blank if using Account No)", key="signin_email")
        account = st.text_input("Account No (leave blank if using Email)", key="signin_account")
        password = st.text_input("Password", type="password", key="signin_password")

        captcha_answer = st.text_input("Answer", key='signin_answer')
        st.write(f"Solve to verify: {st.session_state['captcha_num1']} + "
                 f"{st.session_state['captcha_num2']} = ?")

        submitted = st.form_submit_button("Sign In")
        if submitted:
            msg = ""
            email_id = email_id.strip()
            account = account.strip()
            password = password.strip()
            captcha_answer = captcha_answer.strip()

            if email_id and not validate_email(email_id):
                msg = "❌ Invalid email format."
            elif not email_id and not account:
                msg = "⚠️ Enter either Email or Account No."
            elif email_id and account:
                msg = "⚠️ Enter only one: Email or Account No, not both."
            elif not password:
                msg = "⚠️ Password is required."
            elif not validate_password(password):
                msg = "❌ Password does not meet security requirements."
            else:
                ok, msg = validate_captcha(
                    captcha_answer, st.session_state['captcha_result'])
                if not ok:
                    st.error(msg)
                    return

            if msg:
                st.error(msg)
                return

            with st.spinner("Processing..."):
                status, msg = True, "nop"
                st.error(msg)
                if not status: return

            with st.spinner("📨 Sending acknowledgement email..."):
                status, msg = send_contact_email(email_reg_tmpl, email_id=email_id)

            show_status_dialog(status, msg)


def signup_form():
    st.subheader("Create Account")
    lst = ['signup_email', 'signup_password', 'signup_confirm', 'signup_answer']
    set_captcha_state(lst, 'signup_clear')

    with st.form("signup_form", clear_on_submit=False):
        email_id = st.text_input("Email", key="signup_email")
        password = st.text_input("Password", type="password", key="signup_password")
        confirm_password = st.text_input("Confirm Password", type="password", key="signup_confirm")

        captcha_answer = st.text_input("Answer", key='signup_answer')
        st.write(f"Solve to verify: {st.session_state['captcha_num1']} + "
                 f"{st.session_state['captcha_num2']} = ?")

        submitted = st.form_submit_button("Sign Up")
        if submitted:
            msg = ""
            email_id = email_id.strip()
            password = password.strip()
            confirm_password = confirm_password.strip()
            captcha_answer = captcha_answer.strip()
            if not email_id:
                msg = "⚠️ Email is required."
            elif not validate_email(email_id):
                msg = "❌ Invalid email format."
            elif not password or not confirm_password:
                msg = "⚠️ Passwords are required."
            elif password != confirm_password:
                msg = "❌ Passwords do not match"
            elif not validate_password(password):
                msg = "❌ Password does not meet security requirements."
            else:
                ok, captcha_msg = validate_captcha(
                    captcha_answer, st.session_state['captcha_result'])
                if not ok:
                    st.error(msg)
                    return

            if msg:
                st.error(msg)
                return

            with st.spinner("Creating the account..."):
                status, msg = True, "nop"
                st.error(msg)
                if not status: return

            with st.spinner("📨 Sending acknowledgement email..."):
                status, msg = send_contact_email(email_reg_tmpl, email_id=email_id)

            show_status_dialog(status, msg)


def reset_password_form():
    st.subheader("Reset Password")
    lst = ['reset_email', 'reset_account', 'reset_old_password',
           'reset_new_password', 'reset_confirm_new', 'reset_answer']
    set_captcha_state(lst, 'reset_clear')

    with st.form("reset_form", clear_on_submit=False):
        email_id = st.text_input("Email (leave blank if using Account No)", key="reset_email")
        account = st.text_input("Account No (leave blank if using Email)", key="reset_account")
        old_password = st.text_input("Current Password", type="password", key="reset_old_password")
        new_password = st.text_input("New Password", type="password", key="reset_new_password")
        confirm_new = st.text_input("Confirm New Password", type="password", key="reset_confirm_new")

        captcha_answer = st.text_input("Answer", key='reset_answer')
        st.write(
            f"Solve to verify: {st.session_state['captcha_num1']} + "
            f"{st.session_state['captcha_num2']} = ?"
        )

        submitted = st.form_submit_button("Reset Password")

        if submitted:
            msg = True
            email_id = email_id.strip()
            account = account.strip()
            old_password = old_password.strip()
            new_password = new_password.strip()
            captcha_answer = captcha_answer.strip()
            if email_id and not validate_email(email_id):
                msg = "❌ Invalid email format."
            elif not email_id and not account:
                msg = "Please enter either Email or Account No."
            elif email_id and account:
                msg = "Please enter only one: Email or Account No, not both."
            elif not old_password:
                msg = "Current password is required."
            elif not validate_password(old_password):
                msg = "❌ Current password format is invalid."
            elif not new_password or not confirm_new:
                msg = "New password and confirmation are required."
            elif new_password != confirm_new:
                msg = "New password and confirmation do not match."
            elif not validate_password(new_password):
                msg = "❌ New password does not meet security requirements."
            else:
                ok, msg = validate_captcha(
                    captcha_answer, st.session_state['captcha_result'])
                if not ok:
                    st.error(msg)
                    return

            if msg:
                st.error(msg)
                return

            with st.spinner("Resetting the account password..."):
                status, msg = True, "nop"
                st.error(msg)
                if not status: return

            with st.spinner("📨 Sending confirmation email..."):
                status, msg = send_contact_email(email_reset_tmpl, email_id=email_id)

            show_status_dialog(status, msg)
