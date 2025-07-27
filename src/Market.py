import streamlit as st
from components.layout import render_layout

layout, _ = render_layout("Market")
with layout:
    st.title("📄 Market Page")
    st.write("Content for the Market page.")