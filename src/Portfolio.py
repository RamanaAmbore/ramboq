import streamlit as st
from components.layout import render_layout

layout, _ = render_layout("Portfolio")
with layout:
    st.title("📄 Portfolio Page")
    st.write("Content for the Portfolio page.")