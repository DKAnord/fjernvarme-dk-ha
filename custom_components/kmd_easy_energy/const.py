"""Constants for KMD Easy Energy integration."""

from datetime import timedelta

DOMAIN = "kmd_easy_energy"

CONF_ACCESS_TOKEN = "access_token"
CONF_UTILITY = "utility"
CONF_UTILITY_ID = "utility_id"
CONF_UTILITY_STATUS = "utility_status"
CONF_PORTAL_URL = "portal_url"
CONF_CUSTOMER_NUMBER = "customer_number"
CONF_CUSTOMER_ID = "customer_id"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_LOCATION_NAME = "location_name"
CONF_BONUS_TEMP = "bonus_temp"
CONF_PENALTY_TEMP = "penalty_temp"
CONF_MITID_USERNAME = "mitid_username"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_PRICE_DKK_PER_KWH = "price_dkk_per_kwh"
CONF_PRICE_DKK_PER_M3 = "price_dkk_per_m3"
CONF_MOTIVATION_DKK_PER_KWH_PER_K = "motivation_dkk_per_kwh_per_k"
CONF_NORMAL_HDD_YEAR = "normal_hdd_year"

# KMD plugin API
KMD_API_BASE = "https://easy-energy-plugin-api.kmd.dk"

# Zoom levels matching Novafos / KMD Easy Energy client
ZOOM_YEAR = 0
ZOOM_MONTH = 1
ZOOM_DAY = 2
ZOOM_HOUR = 3

# Consumption type IDs
CONSUMPTION_TYPE_HEATING = 5
CONSUMPTION_TYPE_WATER = 6

# Coordinator poll interval (district heating data is at most hourly)
UPDATE_INTERVAL = timedelta(minutes=30)
TOKEN_MAX_AGE_SECONDS = 45 * 60
TOKEN_WARN_AGE = timedelta(minutes=40)

# Private HA Store version (config/.storage/kmd_easy_energy.<entry_id>)
STORAGE_VERSION = 1

# Bus event with the MitID sync *status only* (sync_state / sync_message and
# has_otp / has_qr flags). The recorder stores every bus event, so the OTP and
# QR are never put on the bus, on entity state, or in the recorder.
EVENT_MITID_CHALLENGE = "kmd_easy_energy_mitid_challenge"

# Internal dispatcher signal + websocket subscription that deliver the live
# MitID challenge (4-digit OTP or both animated QR frames) to the Lovelace card.
# Dispatcher signals and websocket messages are not recorded.
SIGNAL_MITID_CHALLENGE = "kmd_easy_energy_mitid_challenge_live"
WS_TYPE_MITID_SUBSCRIBE = "kmd_easy_energy/mitid/subscribe"

# Volume is the district-heating circulating water (m³), not drinking water.
# SensorDeviceClass.WATER lets the entity be added on the Energy dashboard
# water/volume track; see README / CHANGELOG.
