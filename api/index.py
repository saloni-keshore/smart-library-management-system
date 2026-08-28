"""Vercel serverless entrypoint.

Vercel's @vercel/python builder imports this module and looks for a WSGI
callable named ``app``. All routing is sent here by ``vercel.json``; the
Flask app itself still serves ``/static`` in local/Render runs, but on
Vercel that path is handled by the CDN before it reaches this function.

Render does not use this file at all - it runs ``waitress-serve --call
wsgi:create_app`` per ``render.yaml``.
"""

import os
import sys

# Make the repo root importable regardless of the builder's cwd.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402

app = create_app()
