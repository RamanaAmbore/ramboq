import streamlit as st
from src.utils import isd_codes  # YAML-loaded ISD codes

def contact(body_container):
    with body_container:
        with st.container(key='text-container'):
            st.markdown("### Contact Form")

            with st.form("contact_form", clear_on_submit=True):
                name = st.text_input("Full Name *", max_chars=100)
                email = st.text_input("Email Address *")
                phone_country = st.selectbox(
                    "Country Code",
                    isd_codes
                )
                phone_number = st.text_input("Phone Number")
                query = st.text_area("Your Query *", height=150)

                col1, col2, _ = st.columns([1,1,15])
                submit = col1.form_submit_button("Submit")
                cancel = col2.form_submit_button("Cancel")

                if submit:
                    if not name.strip() or not email.strip() or not query.strip():
                        st.error("Please fill in all mandatory fields (*)")
                    else:
                        selected_code = phone_country.split("(")[-1].strip(")")
                        full_phone = f"{selected_code} {phone_number}"

                        # Placeholder for email sending logic
                        # send_email("query@ramboq.com", name, email, full_phone, query)

                        st.success("✅ Your message has been sent successfully!")

                if cancel:
                    st.warning("Form submission canceled.")
