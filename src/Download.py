import streamlit as st
from components.layout import render_layout

layout, _ = render_layout("Download")
with layout:
    st.title("📄 Download Page")
    st.write("Content for the Download page.")