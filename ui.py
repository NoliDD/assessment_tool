# ui.py
import streamlit as st
from datetime import date
import os

def add_footer(author="Nitesh Oli", contact_email="nitesh.oli@ext.doordash.com", extra=f"v{os.getenv('APP_VERSION','1.0.0')}"):
    year = date.today().year
    st.markdown(f"""
    <style>
      .stApp {{ padding-bottom: 56px; }}
      footer {{ visibility: hidden; }}
      .app-footer {{
        position: fixed; left: 0; right: 0; bottom: 0;
        padding: 10px 16px; text-align: center; font-size: 12.5px;
        background: rgba(0,0,0,0.04); border-top: 1px solid rgba(0,0,0,0.08);
        backdrop-filter: blur(4px);
      }}
      [data-theme="dark"] .app-footer {{
        background: rgba(255,255,255,0.04);
        border-top-color: rgba(255,255,255,0.12);
      }}
    </style>
    <div class="app-footer">
      © {year} • Created by {author} • Issues?
      <a href="mailto:{contact_email}">{contact_email}</a>{' • ' + extra if extra else ''}
    </div>
    """, unsafe_allow_html=True)
