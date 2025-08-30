import streamlit as st

from src.helpers.utils import validate_captcha
from src.utils_streamlit import set_captcha_state


def signin(body_container):
    with body_container:
        with st.container(key='contact_container'):

            # Menu to switch between forms
            menu = st.radio("Choose option:", ["Sign In", "Sign Up", "Reset Password"], horizontal=True)

            # --- SIGN IN FORM ---
            if menu == "Sign In":
                st.subheader("Sign In")
                lst = ['signin_email', 'signin_account', 'signin_password', 'signin_answer']
                set_captcha_state(lst, 'signin_clear')

                with st.form("signin_form", clear_on_submit=False):
                    email = st.text_input("Email (leave blank if using Account No)", key="signin_email")
                    account = st.text_input("Account No (leave blank if using Email)", key="signin_account")
                    password = st.text_input("Password", type="password", key="signin_password")

                    # --- Captcha field ---
                    captcha_answer = st.text_input("Answer", key='signin_answer')
                    st.write(f"Solve to verify: {st.session_state['captcha_num1']} + "
                             f"{st.session_state['captcha_num2']} = ?")
                    print(captcha_answer)

                    submitted = st.form_submit_button("Sign In")
                    if submitted:
                        # Validation: Either Email OR Account No required
                        if not email.strip() and not account.strip():
                            st.error("⚠️ Enter either Email or Account No.")
                            return
                        if email.strip() and account.strip():
                            st.error("⚠️ Enter only one: Email or Account No, not both.")
                            return
                        if not password.strip():
                            st.error("⚠️ Password is required.")
                            return

                        # Captcha validation
                        ok, msg = validate_captcha(captcha_answer.strip(), st.session_state['captcha_result'])
                        if not ok:
                            st.error(msg)
                            return

                        # TODO: Backend validation of email/account + password
                        st.success("✅ Signed in successfully! (Backend pending)")

            # --- SIGN UP FORM ---
            elif menu == "Sign Up":
                st.subheader("Create Account")
                lst = ['signup_email', 'signup_password', 'signup_confirm', 'signup_answer']
                set_captcha_state(lst, 'signup_clear')

                with st.form("signup_form", clear_on_submit=False):
                    email = st.text_input("Email (leave blank if using Account No)", key="signup_email")
                    password = st.text_input("Confirm Password", type="password", key="signup_password")
                    confirm_password = st.text_input("Confirm Password", type="password", key="signup_confirm")

                    # --- Captcha field ---
                    captcha_answer = st.text_input("Answer", key='signup_answer')
                    st.write(f"Solve to verify: {st.session_state['captcha_num1']} + "
                             f"{st.session_state['captcha_num2']} = ?")
                    print(captcha_answer)

                    submitted = st.form_submit_button("Sign Up")
                    if submitted:
                        if not email.strip():
                            st.error("⚠️ Email is required.")
                            return
                        if not password.strip() or not confirm_password.strip():
                            st.error("⚠️ Passwords are required.")
                            return
                        if password != confirm_password:
                            st.error("❌ Passwords do not match")
                            return

                        ok, msg = validate_captcha(captcha_answer.strip(), st.session_state['captcha_result'])
                        if not ok:
                            st.error(msg)
                            return

                        # TODO: Backend user creation
                        st.success("✅ Account created successfully! (Backend pending)")

            # --- RESET PASSWORD FORM ---
            elif menu == "Reset Password":
                st.subheader("Reset Password")
                lst = ['reset_email', 'reset_account', 'reset_old_password',
                       'reset_new_password', 'reset_confirm_new', 'reset_answer']
                set_captcha_state(lst, 'reset_clear')

                with st.form("reset_form", clear_on_submit=False):
                    email = st.text_input("Email (leave blank if using Account No)", key="reset_email")
                    account = st.text_input("Account No (leave blank if using Email)", key="reset_account")
                    old_password = st.text_input("Current Password", type="password", key="reset_old_password")
                    new_password = st.text_input("New Password", type="password", key="reset_new_password")
                    confirm_new = st.text_input("Confirm New Password", type="password", key="reset_confirm_new")

                    # --- Captcha field ---
                    captcha_answer = st.text_input("Answer", key='reset_answer')
                    st.write(f"Solve to verify: {st.session_state['captcha_num1']} + "
                             f"{st.session_state['captcha_num2']} = ?")
                    print(captcha_answer)
