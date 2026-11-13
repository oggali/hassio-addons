"""Shared training-coach rules.

Import :func:`coach.engine.plan_from_payload` for a morning plan and
:func:`coach.engine.evening_from_payload` for the evening recap.
Web, Android, and later the Home Assistant add-on should call those
instead of reimplementing the rules.
"""

__version__ = "0.1.0"
