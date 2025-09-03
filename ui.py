# ui.py
import streamlit as st
from datetime import date
import os


def add_footer(author="Nitesh Oli", contact_email="nitesh.oli@ext.doordash.com", extra=f"v{os.getenv('APP_VERSION','1.0.0')}", lift_for_chat=True):
    """
    Sticky footer that stays visible even on pages with st.chat_input.
    - lift_for_chat=True moves the footer up (e.g., 88px) so it doesn't sit under the chat box.
    """
    year = date.today().year
    bottom_offset = "2px" if lift_for_chat else "0"      # height of chat input + margin
    pad_bottom   = "180px" if lift_for_chat else "56px"   # keep content above footer

    st.markdown(
        f"""
        <style>
          /* prevent overlap with the footer */
          .stApp {{ padding-bottom: {pad_bottom}; }}
          /* hide Streamlit's default footer */
          footer {{ visibility: hidden; }}

          /* our footer */
          .app-footer {{
            position: fixed;
            left: 0; right: 0; bottom: {bottom_offset};
            z-index: 9990;               /* above page content, below modals */
            padding: 10px 16px;
            text-align: center;
            font-size: 12.5px;
            background: rgba(0,0,0,0.04);
            border-top: 1px solid rgba(0,0,0,0.08);
            backdrop-filter: blur(4px);
          }}
          /* dark theme */
          [data-theme="dark"] .app-footer {{
            background: rgba(255,255,255,0.04);
            border-top-color: rgba(255,255,255,0.12);
          }}

          /* slightly higher on narrow screens where the chat input is taller */
          @media (max-width: 900px) {{
            .app-footer {{ bottom: { '96px' if lift_for_chat else '0' }; }}
          }}
        </style>
        <div class="app-footer">
          © {year} • Created by {author} • Issues? <a href="mailto:{contact_email}">{contact_email}</a>{' • ' + extra if extra else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )
    