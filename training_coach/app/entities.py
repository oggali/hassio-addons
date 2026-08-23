"""Entity IDs used by the training coach."""

from __future__ import annotations

from dataclasses import dataclass


OURA_READINESS = "sensor.oura_ring_readiness_score"
OURA_SLEEP = "sensor.oura_ring_sleep_score"
OURA_SLEEP_HRV = "sensor.oura_ring_average_sleep_hrv"
OURA_HRV_BALANCE = "sensor.oura_ring_hrv_balance_score"
OURA_TEMP = "sensor.oura_ring_temperature_deviation"
OURA_REST_MODE = "binary_sensor.oura_ring_rest_mode"
OURA_LAST_WORKOUT_TYPE = "sensor.oura_ring_last_workout_type"
OURA_LAST_WORKOUT_DURATION = "sensor.oura_ring_last_workout_duration"
OURA_LAST_WORKOUT_INTENSITY = "sensor.oura_ring_last_workout_intensity"
OURA_WORKOUTS_TODAY = "sensor.oura_ring_workouts_today"

GARMIN_TRAINING_READINESS = "sensor.garmin_connect_training_readiness"
GARMIN_MORNING_READINESS = "sensor.garmin_connect_morning_training_readiness"
GARMIN_RECOVERY_TIME = "sensor.garmin_connect_recovery_time"
GARMIN_BODY_BATTERY = "sensor.body_battery_most_recent"
GARMIN_HRV_STATUS = "sensor.hrv_status"
GARMIN_HRV_NIGHT = "sensor.garmin_connect_hrv_last_night_average"
GARMIN_HRV_BASELINE = "sensor.garmin_connect_hrv_baseline"
GARMIN_LAST_WORKOUT = "sensor.garmin_connect_last_workout"
GARMIN_SLEEP_SCORE = "sensor.sleep_score"

SESSION_SENSOR = "sensor.training_coach_session"
SUMMARY_SENSOR = "sensor.training_coach_summary"

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
        OURA_LAST_WORKOUT_TYPE,
        OURA_LAST_WORKOUT_DURATION,
        OURA_LAST_WORKOUT_INTENSITY,
        OURA_WORKOUTS_TODAY,
        GARMIN_TRAINING_READINESS,
        GARMIN_MORNING_READINESS,
        GARMIN_RECOVERY_TIME,
        GARMIN_BODY_BATTERY,
        GARMIN_HRV_STATUS,
        GARMIN_HRV_NIGHT,
        GARMIN_HRV_BASELINE,
        GARMIN_LAST_WORKOUT,
        GARMIN_SLEEP_SCORE,
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
