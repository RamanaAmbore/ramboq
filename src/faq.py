import streamlit as st

from src.utils import config
from src.components import create_ruler
import streamlit.components.v1 as components


def faq(body_container):
    with body_container:
        with st.container(key='text-container'):
            st.write(config['faq'])
            st.write(config['nav_flow_title'])
            mermaid_write(config['nav_flow'])
            st.write(config['redemption_flow_title'])
            mermaid_write(config['redemption_flow'])
            st.write(config['succession_flow_title'])
            mermaid_write(config['succession_flow'])

def mermaid_write(mermaid_code):
    # HTML with Mermaid.js injection
    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({{ startOnLoad: true }});
      </script>
    </head>
    <body>
      <div class="mermaid">
        {mermaid_code}
      </div>
    </body>
    </html>
    """

    # Render inside Streamlit
    components.html(html_code, height=500, scrolling=True)