from datetime import date

import streamlit as st

from src.components import render_form
from src.constants import email_contact_tmpl, email_prof_updated_tmpl
from src.helpers.mail_utils import send_email
from src.helpers.utils import ramboq_config
from src.utils_streamlit import show_status_dialog


@st.fragment
def profile():
    with st.container(key="body-container"):
        with st.container(key='contact-container'):
            # Menu to switch between forms
            indx = 0 if st.session_state.profile_updated else 1
            menu = st.radio("Choose option:", ["Display Profile", "Update Profile"], index = indx, horizontal=True)

            # Delegate to the corresponding form function
            if menu == "Display Profile":
                profile_display_form()
            elif menu == "Update Profile":
                profile_update_form()

@st.fragment
def profile_update_form(disabled=None, must=True, called=False):
    if not called:
        st.subheader("Update Profile")
    fields = ['email_id', 'first_name', 'middle_name', 'last_name', 'dob', 'address_line1', 'address_line2',
                       'landmark', 'city', 'state', 'pin_code', 'country', 'ph_country1',
                       'ph_num1', 'ph_country2', 'ph_num2', 'email_id2',
                       'nom_name', 'nom_age', 'relation', 'same',
                       'nom_address_line1', 'nom_address_line2', 'nom_landmark', 'nom_city',
                       'nom_state', 'nom_pin_code', 'nom_country', 'nom_ph_country1',
                       'nom_ph_num1', 'nom_ph_country2',
                      'nom_ph_num2','nom_email_id1', 'nom_email_id2']
    names = ['Primary Email', 'First Name', 'Middle Name', 'Last Name', 'DOB (Date-of-birth)', 'Address Line 1', 'Address Line 2',
                       'Landmark', 'City', 'State', 'Pin/ZIP Code', 'Country', 'ISD Code for Phone Number',
                       'Phone Number', 'ISD Code Backup Phone Number', 'Backup Phone Number', 'Backup Email',
                       'Nominee Name', 'Nominee Age', 'Relation with Account Holder', 'Address same as Account Holder',
                       'Nominee Address Line 1', 'Nominee Address Line 2', 'Nominee Address Landmark', 'Nominee City',
                       'Nominee State', 'Nominee Pin/Zip', 'Nominee Country', 'Nominee Phone ISD Code',
                       'Nominee Phone Number', 'Nominee Backup Phone ISD Code',
                       'Nominee Backup Phone Number','Nominee Email', 'Nominee Backup Email']

    must = [must] * len(names)
    must[0] = False

    if disabled:
        disabled = [disabled] * len(fields)

    v_xref, msg = render_form(fields, names, must, disabled=disabled, form='profile')
    if not v_xref:
        if msg: st.error(msg)
        return


    with st.spinner("📝 Updating profile details..."):
        status, msg = True, "nop"
        if not status:
            st.error(msg)
            return

    with st.spinner("📨 Sending acknowledgement email..."):
        v_xref['subject'] = f"Registration Acknowledgement: Your registration in RamboQ on {date.today()}"
        html_body = email_prof_updated_tmpl.format(**v_xref)

        status, msg = send_email("", v_xref['email_id'], v_xref['subject'], html_body)
        if status:
            msg = "✅ Email has been sent with additional instructions!"
            st.session_state.reg_completed = True

    show_status_dialog(status, msg)



def profile_display_form():
    st.subheader("Display Profile")

    profile_update_form(disabled=True,must=False, called=True)


