"""The api image must ship the Google STT client (core's stt-google extra)."""

import importlib

import pytest

pytestmark = pytest.mark.unit


def test_google_speech_client_importable_in_api_env():
    importlib.import_module("google.cloud.speech_v2")
