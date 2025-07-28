import streamlit as st


def route():
    # Content with 10px vertical spacing
    st.markdown("<div>", unsafe_allow_html=True)
    with st.container():
        if st.session_state.nav_active == "About":
            st.write("🏢 Welcome to Ramboq — empowering smarter investments.")
        elif st.session_state.nav_active == "Market":
            st.write("📈 Market analysis and live charts.")
        elif st.session_state.nav_active == "Performance":
            st.write("🧮 Performance breakdown and asset overview.")
        elif st.session_state.nav_active == "Update":
            st.write("🧮 Updates coming soon...")
        elif st.session_state.nav_active == "Contact":
            st.write("📞 Contact our team or request a demo.")
    st.markdown("</div>", unsafe_allow_html=True)
