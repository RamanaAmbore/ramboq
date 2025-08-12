import streamlit as st

from src.utils import config
from src.components import create_ruler
import streamlit.components.v1 as components


def faq(body_container):
    with body_container:
        with st.container(key='text-container'):
            st.write(config['faq'])
            st.write(config['nav_flow_title'])
            mermaid_write(config['nav_flow'], height=400)
            st.write(config['redemption_flow_title'])
            mermaid_write(config['redemption_flow'], height=300)
            st.write(config['succession_flow_title'])
            mermaid_write(config['succession_flow'], height=300)
            create_ruler()

def mermaid_write(mermaid_code, height=500):
    # HTML with Mermaid.js injection
    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        /* Override ALL Mermaid nodes inside the iframe */
        .mermaid .node rect {{
          fill: #fffdfa !important;
          stroke: gray !important;
          stroke-width: 1px !important;
        }}
        .mermaid .node text {{
          fill: #315062 !important;
          font-weight: bold !important;
          font-size: .9rem !important;
        }}
      </style>

      <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({{ startOnLoad: true }});

        /* After mermaid renders, ensure rects have rounded corners (rx/ry attributes) */
        function setRoundedCorners() {{
          document.querySelectorAll('.mermaid svg g.node rect').forEach(r => {{
            r.setAttribute('rx', '8');
            r.setAttribute('ry', '8');
          }});
        }}

        // Try once after load and also observe mutations (safe for dynamic re-renders)
        window.addEventListener('load', () => {{
          setTimeout(setRoundedCorners, 200);
          const obs = new MutationObserver(setRoundedCorners);
          obs.observe(document.body, {{ childList: true, subtree: true }});
        }});
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
    components.html(html, height=height, scrolling=True)