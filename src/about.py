import streamlit as st
from components.layout import render_layout

layout, _ = render_layout("About")
with layout:
    st.title("📄 About Page")
    st.write("Content for the About page.")