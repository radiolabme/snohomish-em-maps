"""Shared pytest configuration for Snohomish County map tests."""

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "network: requires network access")
