import streamlit as st

from src.helpers.utils import validate_captcha, validate_password, validate_email
from src.utils_streamlit import set_captcha_state, show_status_dialog


@st.fragment
def signin():
    with st.container(key="body-container"):
        with st.container(key='contact-container'):

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

                    submitted = st.form_submit_button("Sign In")
                    if submitted:
                        errors = []

                        # Validation: Either Email OR Account No required
                        if email.strip() and not validate_email(email.strip()):
                            errors.append("❌ Invalid email format.")
                        if not email.strip() and not account.strip():
                            errors.append("⚠️ Enter either Email or Account No.")
                        if email.strip() and account.strip():
                            errors.append("⚠️ Enter only one: Email or Account No, not both.")
                        if not password.strip():
                            errors.append("⚠️ Password is required.")
                        elif not validate_password(password.strip()):
                            errors.append("❌ Password does not meet security requirements.")

                        # Captcha validation
                        ok, msg = validate_captcha(captcha_answer.strip(), st.session_state['captcha_result'])
                        if not ok:
                            errors.append(msg)

                        if errors:
                            for e in errors:
                                st.error(e)
                        else:
                            show_status_dialog(True, "Signed in successfully!")

            # --- SIGN UP FORM ---
            elif menu == "Sign Up":
                st.subheader("Create Account")
                lst = ['signup_email', 'signup_password', 'signup_confirm', 'signup_answer']
                set_captcha_state(lst, 'signup_clear')

                with st.form("signup_form", clear_on_submit=False):
                    email = st.text_input("Email", key="signup_email")
                    password = st.text_input("Password", type="password", key="signup_password")
                    confirm_password = st.text_input("Confirm Password", type="password", key="signup_confirm")

                    # --- Captcha field ---
                    captcha_answer = st.text_input("Answer", key='signup_answer')
                    st.write(f"Solve to verify: {st.session_state['captcha_num1']} + "
                             f"{st.session_state['captcha_num2']} = ?")

                    submitted = st.form_submit_button("Sign Up")
                    if submitted:
                        errors = []

                        if not email.strip():
                            errors.append("⚠️ Email is required.")
                        elif not validate_email(email.strip()):
                            errors.append("❌ Invalid email format.")

                        if not password.strip() or not confirm_password.strip():
                            errors.append("⚠️ Passwords are required.")
                        elif password != confirm_password:
                            errors.append("❌ Passwords do not match")
                        elif not validate_password(password.strip()):
                            errors.append("❌ Password does not meet security requirements.")

                        ok, msg = validate_captcha(captcha_answer.strip(), st.session_state['captcha_result'])
                        if not ok:
                            errors.append(msg)

                        if errors:
                            for e in errors:
                                st.error(e)
                        else:
                            # TODO: Backend user creation
                            show_status_dialog(True, "Account created successfully!")

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
                    st.write(
                        f"Solve to verify: {st.session_state['captcha_num1']} + "
                        f"{st.session_state['captcha_num2']} = ?"
                    )

                    submit_btn = st.form_submit_button("Reset Password")

                    if submit_btn:
                        errors = []

                        # 1. Email or Account validation
                        if email.strip() and not validate_email(email.strip()):
                            errors.append("❌ Invalid email format.")
                        elif not email.strip() and not account.strip():
                            errors.append("Please enter either Email or Account No.")
                        elif email.strip() and account.strip():
                            errors.append("Please enter only one: Email or Account No, not both.")

                        # 2. Old password required
                        if not old_password.strip():
                            errors.append("Current password is required.")
                        elif not validate_password(old_password.strip()):
                            errors.append("❌ Current password format is invalid.")

                        # 3. Password validations
                        if not new_password.strip() or not confirm_new.strip():
                            errors.append("New password and confirmation are required.")
                        elif new_password != confirm_new:
                            errors.append("New password and confirmation do not match.")
                        elif not validate_password(new_password.strip()):
                            errors.append("❌ New password does not meet security requirements.")

                        # 4. Captcha validation
                        ok, msg = validate_captcha(captcha_answer.strip(), st.session_state['captcha_result'])
                        if not ok:
                            errors.append(msg)

                        if errors:
                            for e in errors:
                                st.error(e)
                        else:
                            # TODO: Backend reset logic
                            show_status_dialog(True, "Password reset successful!")
