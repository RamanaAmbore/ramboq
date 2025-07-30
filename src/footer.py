import streamlit as st

from src.components import markdown

footer_name = '© Rambo Quant Investments LLP'
footer_mobile_text2 = 'Markets carry risk.'


footer_desktop_text2 = 'LLDIN00123456'
footer_desktop_text3 = 'Disclaimer: Investment in markets is subject to risk. Past performance is not indicative of future results.'

def footer():
    with st.container(key='footer-container'):
        st.markdown(
            f"""
            <p class="footer-desktop">
                {footer_name}
                <span style='color:#007ACC;'> | </span>
                {footer_desktop_text2}
                <span style='color:#007ACC;'> | </span>
                {footer_desktop_text3}
            </p>
            <p class="footer-mobile">
                {footer_name}
                <span style='color:#007ACC;'> | </span>
                {footer_mobile_text2}
            </p>
            """,
            unsafe_allow_html=True
        )
