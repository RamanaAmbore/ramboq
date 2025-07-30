import streamlit as st

from src.utils import constants


def footer():
    footer_name = f"© {constants['footer_name']}"
    with st.container(key='footer-container'):
        st.markdown(
            f"""
            <p class="footer-desktop">
                {footer_name}
                <span style='color:#007ACC;'> | </span>
                {constants['footer_desktop_text2']}
                <span style='color:#007ACC;'> | </span>
                {constants['footer_desktop_text3']}
            </p>
            <p class="footer-mobile">
                {footer_name}
                <span style='color:#007ACC;'> | </span>
                {constants['footer_mobile_text2']}
            </p>
            """,
            unsafe_allow_html=True
        )
