import streamlit as st

from src.utils import config


def footer(footer_container):
    footer_name = f"© {config['footer_name']}"
    with footer_container:
        st.markdown(
            f"""
            <p class="footer-desktop">
                {footer_name}
                <span style='color:#E66414'> | </span>
                {config['footer_desktop_text2']}
                <span style='color:#E66414'> | </span>
                {config['footer_desktop_text3']}
            </p>
            <p class="footer-mobile">
                {footer_name}
                <span style='color:#E66414'> | </span>
                {config['footer_mobile_text2']}
            </p>
            """,
            unsafe_allow_html=True
        )
