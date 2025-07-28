import streamlit as st

from src.components import markdown


def footer():
    with st.container(key='footer-container'):
        markdown(
            """
                © Rambo Quant Investments LLP
                <span style='color:#007ACC;'> | </span>
                LLDIN00123456
                <span style='color:#007ACC;'> | </span>
                Disclaimer: Investment in markets is subject to risk. Past performance is not indicative of future results.
            """,
            tag='p',
            style='font-size:15px;',
            key='footer-desktop'
        )

        markdown("""
                      © Rambo Quant Investments LLP
                      <span style='color:#007ACC;'> | </span>
                      LLDIN00123456
                      <span style='color:#007ACC;'> | </span>
                      Markets carry risk.
                  """,
                 key='footer-mobile',
                 )
