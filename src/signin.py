import streamlit as st

def signin(body_container):
    with body_container:
        if "captcha_num1" not in st.session_state:
            st.session_state.captcha_num1 = random.randint(1, 9)
            st.session_state.captcha_num2 = random.randint(1, 9)
        with st.container(key="contact-container"):
            # Menu to switch between forms
            menu = st.radio("Choose option:", ["Sign In", "Sign Up", "Reset Password"], horizontal=True)

            # --- SIGN IN FORM ---
            if menu == "Sign In":
                st.subheader("Sign In")

                with st.form("signin_form", clear_on_submit=False):
                    email = st.text_input("Email")
                    password = st.text_input("Password", type="password")
                    submitted = st.form_submit_button("Sign In")

                    if submitted:
                        st.info("👉 Frontend only: sign-in backend pending.")

            # --- SIGN UP FORM ---
            elif menu == "Sign Up":
                st.subheader("Create Account")

                with st.form("signup_form", clear_on_submit=False):
                    email = st.text_input("Email")
                    password = st.text_input("Password", type="password")
                    confirm_password = st.text_input("Confirm Password", type="password")
                    submitted = st.form_submit_button("Sign Up")

                    if submitted:
                        if password != confirm_password:
                            st.error("Passwords do not match ❌")
                        else:
                            st.info("👉 Frontend only: account creation backend pending.")

            # --- RESET PASSWORD FORM ---
            elif menu == "Reset Password":
                st.subheader("Reset Password")

                with st.form("reset_form", clear_on_submit=False):
                    email = st.text_input("Registered Email")
                    new_password = st.text_input("New Password", type="password")
                    confirm_new = st.text_input("Confirm New Password", type="password")
                    submitted = st.form_submit_button("Reset Password")

                    if submitted:
                        if new_password != confirm_new:
                            st.error("Passwords do not match ❌")
                        else:
                            st.info("👉 Frontend only: reset backend pending.")


def profile_layout(mode="view", profile_data=None):
    """
    mode: "add", "update", or "view"
    profile_data: dict with user details (for update/view)
    """

    st.subheader("User Profile")

    if mode == "view":
        # Display profile in read-only format
        if not profile_data:
            st.warning("No profile found.")
            return

        st.text(f"Name: {profile_data['first_name']} {profile_data['last_name']}")
        st.text(f"DOB: {profile_data['dob']}")
        st.text(f"Nominee: {profile_data['nominee_name']}")
        st.text(f"Nominee Contact: {profile_data['nominee_contact']}")
        st.text(f"Address: {profile_data['address_line1']}, {profile_data.get('address_line2', '')}")
        st.text(f"City: {profile_data['city']}, State: {profile_data['state']}, Pin: {profile_data['pin']}")
        st.text(f"Country: {profile_data['country']}")
        st.text(
            f"Contact Number: {profile_data['contact_number']}, Backup: {profile_data.get('backup_contact_number', '')}")
        return

    # For add or update → form
    with st.form(key=f"profile_form_{mode}"):
        first_name = st.text_input("First Name", value=profile_data.get("first_name", "") if profile_data else "")
        last_name = st.text_input("Last Name", value=profile_data.get("last_name", "") if profile_data else "")
        dob = st.date_input("Date of Birth", value=profile_data.get("dob", None) if profile_data else None)

        nominee_name = st.text_input("Nominee Name", value=profile_data.get("nominee_name", "") if profile_data else "")
        nominee_address = st.text_area("Nominee Address",
                                       value=profile_data.get("nominee_address", "") if profile_data else "")
        nominee_contact = st.text_input("Nominee Contact",
                                        value=profile_data.get("nominee_contact", "") if profile_data else "")

        st.markdown("**Address Details**")
        address_line1 = st.text_input("Address Line 1",
                                      value=profile_data.get("address_line1", "") if profile_data else "")
        address_line2 = st.text_input("Address Line 2 (Optional)",
                                      value=profile_data.get("address_line2", "") if profile_data else "")
        city = st.text_input("City", value=profile_data.get("city", "") if profile_data else "")
        state = st.text_input("State", value=profile_data.get("state", "") if profile_data else "")
        pin = st.text_input("PIN Code", value=profile_data.get("pin", "") if profile_data else "")
        country = st.text_input("Country", value=profile_data.get("country", "") if profile_data else "")

        st.markdown("**Contact Details**")
        contact_number = st.text_input("Contact Number",
                                       value=profile_data.get("contact_number", "") if profile_data else "")
        backup_contact_number = st.text_input("Backup Contact Number (Optional)",
                                              value=profile_data.get("backup_contact_number",
                                                                     "") if profile_data else "")

        submitted = st.form_submit_button("Save" if mode == "add" else "Update")
        if submitted:
            st.session_state.profile_present = True
            st.session_state.validated = False  # validation may be an admin process
            st.success(f"Profile {'created' if mode == 'add' else 'updated'} successfully!")
            # here we’d call backend to save to DB
