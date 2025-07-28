import streamlit as st
from components.layout import render_layout

layout, _ = render_layout("Contact")
with layout:
    st.title("📄 Contact Page")
    st.write("Content for the Contact page.")