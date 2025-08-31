import streamlit as st

from src.helpers.utils import ramboq_config


def footer():
    footer_name = f"© {ramboq_config['footer_name']}"
    with st.container(key='footer-container'):
        st.markdown(
            f"""
            <p class="footer-desktop">
                {footer_name}
                <span style='color:#ef9309'> | </span>
                {ramboq_config['footer_desktop_text2']}
                <span style='color:#ef9309'> | </span>
                {ramboq_config['footer_desktop_text3']}
            </p>
            <p class="footer-mobile">
                {footer_name}
                <span style='color:#ef9309'> | </span>
                {ramboq_config['footer_mobile_text2']}
            </p>
            """,
            unsafe_allow_html=True
        )
