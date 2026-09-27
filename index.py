"""Punto de entrada para Vercel (detecta `app` en index.py). Localmente: uvicorn index:app --reload"""
from backend.app.main import app  # noqa: F401
