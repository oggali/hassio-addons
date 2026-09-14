"""Entity IDs used by the training coach."""

from __future__ import annotations

from dataclasses import dataclass


OURA_READINESS = "sensor.oura_ring_readiness_score"
OURA_SLEEP = "sensor.oura_ring_sleep_score"
OURA_SLEEP_HRV = "sensor.oura_ring_average_sleep_hrv"
OURA_HRV_BALANCE = "sensor.oura_ring_hrv_balance_score"
OURA_TEMP = "sensor.oura_ring_temperature_deviation"
OURA_REST_MODE = "binary_sensor.oura_ring_rest_mode"
OURA_ACTIVITY_SCORE = "sensor.oura_ring_activity_score"
OURA_STEPS = "sensor.oura_ring_steps"
OURA_ACTIVE_CALORIES = "sensor.oura_ring_active_calories"
OURA_TOTAL_CALORIES = "sensor.oura_ring_total_calories"
OURA_HIGH_ACTIVITY_TIME = "sensor.oura_ring_high_activity_time"
OURA_MEDIUM_ACTIVITY_TIME = "sensor.oura_ring_medium_activity_time"

GARMIN_TRAINING_READINESS = "sensor.garmin_connect_training_readiness"
GARMIN_MORNING_READINESS = "sensor.garmin_connect_morning_training_readiness"
GARMIN_RECOVERY_TIME = "sensor.garmin_connect_recovery_time"
GARMIN_BODY_BATTERY = "sensor.body_battery_most_recent"
GARMIN_HRV_STATUS = "sensor.hrv_status"
GARMIN_HRV_NIGHT = "sensor.garmin_connect_hrv_last_night_average"
GARMIN_HRV_BASELINE = "sensor.garmin_connect_hrv_baseline"
GARMIN_LAST_ACTIVITY = "sensor.garmin_connect_last_activity"
GARMIN_LAST_ACTIVITIES = "sensor.garmin_connect_last_activities"
GARMIN_LAST_ACTIVITY_FALLBACK = "sensor.last_activity"
GARMIN_LAST_ACTIVITIES_FALLBACK = "sensor.last_activities"
GARMIN_TOTAL_STEPS = "sensor.garmin_connect_total_steps"
GARMIN_YESTERDAY_STEPS = "sensor.garmin_connect_yesterday_steps"
GARMIN_ACTIVE_CALORIES = "sensor.garmin_connect_active_calories"
GARMIN_TOTAL_CALORIES = "sensor.garmin_connect_total_calories"
GARMIN_INTENSITY_MINUTES = "sensor.garmin_connect_total_intensity_minutes"
GARMIN_SLEEP_SCORE = "sensor.sleep_score"
STRAVA_LATEST_SPLITS = "sensor.strava_latest_splits"

# Older Garmin entity IDs (unprefixed) still used on some installs.
GARMIN_TOTAL_STEPS_FALLBACK = "sensor.total_steps"
GARMIN_ACTIVE_CALORIES_FALLBACK = "sensor.active_calories"
GARMIN_INTENSITY_MINUTES_FALLBACK = "sensor.total_intensity_minutes"

SESSION_SENSOR = "sensor.training_coach_session"
SUMMARY_SENSOR = "sensor.training_coach_summary"
GOAL_SENSOR = "sensor.training_coach_goal"
FEEDBACK_SENSOR = "sensor.training_coach_feedback"

RACE_DATE_HELPER = "input_datetime.training_coach_race_date"
RACE_DISTANCE_HELPER = "input_select.training_coach_race_distance"
TARGET_TIME_HELPER = "input_text.training_coach_target_time"
WEEKLY_LONG_HELPER = "input_number.training_coach_weekly_long_runs"
WEEKLY_QUALITY_HELPER = "input_number.training_coach_weekly_quality_runs"
WEEKLY_STRENGTH_HELPER = "input_number.training_coach_weekly_strength"
WEEKLY_REST_HELPER = "input_number.training_coach_weekly_rest_days"
FEELING_HELPER = "input_select.training_coach_feeling"
DID_PLAN_HELPER = "input_select.training_coach_did_plan"
SKIP_REASON_HELPER = "input_select.training_coach_skip_reason"

PREF_HELPER_IDS = (
    RACE_DATE_HELPER,
    RACE_DISTANCE_HELPER,
    TARGET_TIME_HELPER,
    WEEKLY_LONG_HELPER,
    WEEKLY_QUALITY_HELPER,
    WEEKLY_STRENGTH_HELPER,
    WEEKLY_REST_HELPER,
)
FEEDBACK_HELPER_IDS = (
    FEELING_HELPER,
    DID_PLAN_HELPER,
    SKIP_REASON_HELPER,
)

STRAVA_RECENT_COUNT = 10


@dataclass(frozen=True)
class StravaSlotIds:
    activity: str
    date: str
    distance: str
    moving_time: str
    elapsed_time: str
    average_heartrate: str
    max_heartrate: str


def strava_slot_suffix(index: int) -> str:
    """Index 0 is unsuffixed; 1..9 become _2 .. _10."""
    if index <= 0:
        return ""
    return f"_{index + 1}"


def strava_slot_ids(prefix: str, index: int) -> StravaSlotIds:
    suffix = strava_slot_suffix(index)
    base = f"{prefix}_recent_activity{suffix}"
    return StravaSlotIds(
        activity=base,
        date=f"{base}_date",
        distance=f"{base}_distance",
        moving_time=f"{base}_moving_time",
        elapsed_time=f"{base}_elapsed_time",
        average_heartrate=f"{base}_average_heartrate",
        max_heartrate=f"{base}_max_heartrate",
    )


def all_strava_slot_ids(prefix: str) -> list[StravaSlotIds]:
    return [strava_slot_ids(prefix, i) for i in range(STRAVA_RECENT_COUNT)]


def recovery_entity_ids() -> list[str]:
    return [
        OURA_READINESS,
        OURA_SLEEP,
        OURA_SLEEP_HRV,
        OURA_HRV_BALANCE,
        OURA_TEMP,
        OURA_REST_MODE,
        OURA_ACTIVITY_SCORE,
        OURA_STEPS,
        OURA_ACTIVE_CALORIES,
        OURA_TOTAL_CALORIES,
        OURA_HIGH_ACTIVITY_TIME,
        OURA_MEDIUM_ACTIVITY_TIME,
        GARMIN_TRAINING_READINESS,
        GARMIN_MORNING_READINESS,
        GARMIN_RECOVERY_TIME,
        GARMIN_BODY_BATTERY,
        GARMIN_HRV_STATUS,
        GARMIN_HRV_NIGHT,
        GARMIN_HRV_BASELINE,
        GARMIN_LAST_ACTIVITY,
        GARMIN_LAST_ACTIVITIES,
        GARMIN_LAST_ACTIVITY_FALLBACK,
        GARMIN_LAST_ACTIVITIES_FALLBACK,
        GARMIN_TOTAL_STEPS,
        GARMIN_TOTAL_STEPS_FALLBACK,
        GARMIN_YESTERDAY_STEPS,
        GARMIN_ACTIVE_CALORIES,
        GARMIN_ACTIVE_CALORIES_FALLBACK,
        GARMIN_TOTAL_CALORIES,
        GARMIN_INTENSITY_MINUTES,
        GARMIN_INTENSITY_MINUTES_FALLBACK,
        GARMIN_SLEEP_SCORE,
        STRAVA_LATEST_SPLITS,
    ]


def tracked_entity_ids(strava_prefix: str) -> list[str]:
    ids = list(recovery_entity_ids())
    ids.extend(
        [
            f"{strava_prefix}_run_date",
            f"{strava_prefix}_run_distance",
            f"{strava_prefix}_run_moving_time",
            f"{strava_prefix}_weight_training_date",
            f"{strava_prefix}_weight_training_moving_time",
        ]
    )
    for slot in all_strava_slot_ids(strava_prefix):
        ids.extend(
            [
                slot.activity,
                slot.date,
                slot.distance,
                slot.moving_time,
                slot.elapsed_time,
                slot.average_heartrate,
                slot.max_heartrate,
            ]
        )
    return ids
