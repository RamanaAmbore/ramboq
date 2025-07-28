import streamlit as st
from components.layout import render_layout

layout, _ = render_layout("Blog")
with layout:
    st.title("📄 Blog Page")
    st.write("Content for the Blog page.")