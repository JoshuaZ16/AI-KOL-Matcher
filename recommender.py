# recommender.py
# Backward-compatible wrapper. The service implementation now lives in api.py.

from api import get_filter_options, recommend

__all__ = ["get_filter_options", "recommend"]
