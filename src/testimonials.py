import base64
import uuid
from datetime import date
from pathlib import Path

import streamlit as st
import yaml

from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import ramboq_deploy

logger = get_logger(__name__)

TESTIMONIALS_FILE = "setup/yaml/testimonials.yaml"
TESTIMONIALS_IMG_DIR = "setup/images/testimonials"


def _load_testimonials():
    if not Path(TESTIMONIALS_FILE).exists():
        return []
    with open(TESTIMONIALS_FILE, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    return data.get('testimonials', [])


def _save_testimonials(items):
    Path(TESTIMONIALS_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(TESTIMONIALS_FILE, 'w', encoding='utf-8') as f:
        yaml.dump({'testimonials': items}, f, allow_unicode=True, default_flow_style=False)


def _save_image(uploaded_file):
    img_dir = Path(TESTIMONIALS_IMG_DIR)
    img_dir.mkdir(parents=True, exist_ok=True)
    ext = uploaded_file.name.rsplit('.', 1)[-1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    with open(img_dir / filename, 'wb') as f:
        f.write(uploaded_file.getbuffer())
    return filename


def _get_image_b64(filename):
    path = Path(TESTIMONIALS_IMG_DIR) / filename
    if not path.exists():
        return None
    ext = filename.rsplit('.', 1)[-1].lower()
    mime = 'jpeg' if ext in ('jpg', 'jpeg') else ext
    with open(path, 'rb') as f:
        data = f.read()
    return f"data:image/{mime};base64,{base64.b64encode(data).decode()}"


def _is_admin():
    pin_cfg = ramboq_deploy.get('testimonials_admin_pin', '')
    return bool(pin_cfg) and st.session_state.get('t_admin_auth', False)


def _admin_auth_section():
    pin_cfg = ramboq_deploy.get('testimonials_admin_pin', '')
    if not pin_cfg:
        return

    if not st.session_state.get('t_admin_auth', False):
        with st.expander("Admin", expanded=False):
            entered = st.text_input("Admin PIN", type='password', key='t_pin_input')
            if st.button("Login", key='t_login_btn'):
                if entered == str(pin_cfg):
                    st.session_state['t_admin_auth'] = True
                    st.rerun()
                else:
                    st.error("Incorrect PIN.")
    else:
        if st.button("Logout Admin", key='t_logout_btn'):
            st.session_state['t_admin_auth'] = False
            st.session_state.pop('t_edit_id', None)
            st.rerun()


def _admin_form(items):
    edit_id = st.session_state.get('t_edit_id')
    edit_item = next((t for t in items if t['id'] == edit_id), None) if edit_id else None

    label = f"Edit: {edit_item['name']}" if edit_item else "Add Testimonial"
    with st.expander(label, expanded=True):
        with st.form("t_form", clear_on_submit=True):
            name = st.text_input("Name *", value=edit_item['name'] if edit_item else '')
            role = st.text_input("Role / Designation", value=edit_item.get('role', '') if edit_item else '')
            text = st.text_area(
                "Testimonial (markdown supported)",
                value=edit_item.get('text', '') if edit_item else '',
                height=150
            )
            uploaded = st.file_uploader("Photo (optional — replaces existing)", type=['png', 'jpg', 'jpeg'])
            submitted = st.form_submit_button("Save")

            if submitted:
                if not name.strip():
                    st.error("Name is required.")
                else:
                    img_filename = edit_item.get('image', '') if edit_item else ''
                    if uploaded:
                        img_filename = _save_image(uploaded)

                    if edit_item:
                        for t in items:
                            if t['id'] == edit_id:
                                t.update({
                                    'name': name.strip(),
                                    'role': role.strip(),
                                    'text': text.strip(),
                                    'image': img_filename,
                                })
                                break
                        st.session_state.pop('t_edit_id', None)
                    else:
                        items.append({
                            'id': uuid.uuid4().hex[:8],
                            'name': name.strip(),
                            'role': role.strip(),
                            'text': text.strip(),
                            'image': img_filename,
                            'date': str(date.today()),
                        })

                    _save_testimonials(items)
                    st.rerun()

        if edit_item and st.button("Cancel", key='t_cancel_btn'):
            st.session_state.pop('t_edit_id', None)
            st.rerun()


def testimonials():
    with st.container(key="body-container"):
        with st.container(key='text-container'):
            st.subheader(":speech_balloon: Testimonials", divider='rainbow')

            _admin_auth_section()

            items = _load_testimonials()

            if _is_admin():
                _admin_form(items)
                st.markdown("---")

            if not items:
                st.info("No testimonials yet.")
                return

            for t in items:
                with st.container():
                    if t.get('image'):
                        img_col, text_col = st.columns([1, 6])
                        b64 = _get_image_b64(t['image'])
                        if b64:
                            img_col.markdown(
                                f"<img src='{b64}' style='width:72px;height:72px;"
                                f"object-fit:cover;border-radius:50%;margin-top:6px;'>",
                                unsafe_allow_html=True
                            )
                    else:
                        text_col = st.container()

                    with text_col:
                        name_line = f"**{t['name']}**"
                        if t.get('role'):
                            name_line += f" — *{t['role']}*"
                        st.markdown(name_line)
                        if t.get('date'):
                            st.caption(t['date'])
                        st.markdown(t.get('text', ''))

                    if _is_admin():
                        c1, c2, _ = st.columns([1, 1, 5])
                        if c1.button("Edit", key=f"t_edit_{t['id']}"):
                            st.session_state['t_edit_id'] = t['id']
                            st.rerun()
                        if c2.button("Delete", key=f"t_del_{t['id']}"):
                            if t.get('image'):
                                img_path = Path(TESTIMONIALS_IMG_DIR) / t['image']
                                if img_path.exists():
                                    img_path.unlink()
                            items = [x for x in items if x['id'] != t['id']]
                            _save_testimonials(items)
                            st.rerun()

                    st.divider()
