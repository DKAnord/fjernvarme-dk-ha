"""Constants for KMD Easy Energy integration."""

DOMAIN = "kmd_easy_energy"

# Legacy key: KMD access tokens are no longer stored (session-based sync).
# Kept only so migration can remove it from old config entries.
CONF_ACCESS_TOKEN = "access_token"
CONF_UTILITY = "utility"
CONF_UTILITY_ID = "utility_id"
CONF_UTILITY_STATUS = "utility_status"
CONF_PORTAL_URL = "portal_url"
CONF_CUSTOMER_NUMBER = "customer_number"
CONF_CUSTOMER_ID = "customer_id"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
# Utility (værk) coordinates from utilities.json: metadata and the last-resort
# Open-Meteo location. Only CONF_LATITUDE/CONF_LONGITUDE in *options* are an
# explicit user override (see outdoor_temp.resolve_location).
CONF_UTILITY_LATITUDE = "utility_latitude"
CONF_UTILITY_LONGITUDE = "utility_longitude"
# Optional HA outdoor temperature sensor (long-term statistics, local-first).
CONF_OUTDOOR_TEMP_ENTITY = "outdoor_temp_entity"
CONF_LOCATION_NAME = "location_name"
CONF_BONUS_TEMP = "bonus_temp"
CONF_PENALTY_TEMP = "penalty_temp"
CONF_MITID_USERNAME = "mitid_username"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_PRICE_DKK_PER_KWH = "price_dkk_per_kwh"
CONF_PRICE_DKK_PER_M3 = "price_dkk_per_m3"
CONF_MOTIVATION_DKK_PER_KWH_PER_K = "motivation_dkk_per_kwh_per_k"
CONF_NORMAL_HDD_YEAR = "normal_hdd_year"
CONF_SYNC_REMINDER = "sync_reminder"
DEFAULT_SYNC_REMINDER = True

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

# Session-based sync: KMD only issues a ~1 h access token (no refresh token),
# so the integration never polls KMD in the background. Each sync is one MitID
# login -> fetch -> token discarded. The coordinator only re-reads its cache.
UPDATE_INTERVAL = None

# Hourly history months fetched per sync (first sync = full year backfill).
FIRST_SYNC_BACKFILL_MONTHS = 12
SYNC_BACKFILL_MONTHS = 3

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


# Bundled Lovelace card. Copied to <config>/www/js/ and served under /local/js/.
# Home Assistant caches /local for 31 days (Cache-Control: public, max-age=2678400),
# so the Lovelace resource URL must include ?v=<manifest version> after each
# card update. Without it, a browser or Companion app can keep a stale card
# (v0.2.x reads the removed mitid_qr_svg attribute and shows no QR).
CARD_JS_FILENAME = "kmd-easy-energy-card.js"
CARD_RESOURCE_PATH = f"/local/js/{CARD_JS_FILENAME}"

# Volume is the district-heating circulating water (m³), not drinking water.
# SensorDeviceClass.WATER lets the entity be added on the Energy dashboard
# water/volume track; see README / CHANGELOG.

# ---------------------------------------------------------------------------
# Backends. "kmd" = KMD Easy Energy (MitID, session-based). "eforsyning" =
# E|Forsyning (eforsyning.dk / dff-edb.dk; forbrugernummer + webpinkode).
# "wattson" = Watts On (Watts A/S app backend; Azure AD B2C refresh token),
# used by Aalborg Forsyning (confirmed live) and other Watts On district-heating utilities.
# ---------------------------------------------------------------------------
CONF_BACKEND = "backend"
BACKEND_KMD = "kmd"
BACKEND_EFORSYNING = "eforsyning"
BACKEND_WATTSON = "wattson"
BACKENDS = (BACKEND_KMD, BACKEND_EFORSYNING, BACKEND_WATTSON)
# Backends that log in without MitID and may sync automatically every day.
AUTO_SYNC_BACKENDS = (BACKEND_EFORSYNING, BACKEND_WATTSON)

# E|Forsyning credentials (stored in the config entry like other HA
# integrations store passwords; never logged, redacted in diagnostics).
CONF_EF_USERNAME = "eforsyning_username"  # forbrugernummer
CONF_EF_PASSWORD = "eforsyning_password"  # webpinkode
CONF_EF_SUPPLIER_ID = "eforsyning_supplier_id"  # GetVaerkSettings forsyningid
CONF_EF_INSTALLATION_ID = "eforsyning_installation_id"
EFORSYNING_BASE_URL = "https://eforsyning.dk/"

# Watts On. The refresh token is a credential: stored in the config entry
# (rotated tokens are persisted), never logged, redacted in diagnostics.
# The Watts password is never asked for or stored.
CONF_WATTS_REFRESH_TOKEN = "wattson_refresh_token"
CONF_WATTS_REFRESH_EXPIRES_AT = "wattson_refresh_expires_at"
CONF_WATTS_USER_ID = "wattson_user_id"
CONF_WATTS_DEVICE_ID = "wattson_device_id"
CONF_WATTS_ENDPOINT = "wattson_endpoint"  # advanced override (path template)
CONF_WATTS_ENERGY_UNIT = "wattson_energy_unit"  # auto | kWh | MWh | GJ
WATTS_ENERGY_UNITS = ("auto", "kWh", "MWh", "GJ")

# Automatic sync (only for backends that need no MitID: E|Forsyning, Watts On).
CONF_AUTO_SYNC = "auto_sync"
CONF_AUTO_SYNC_HOUR = "auto_sync_hour"
DEFAULT_AUTO_SYNC = True
DEFAULT_AUTO_SYNC_HOUR = 6
# Weekend reminder default per backend (E|Forsyning syncs itself daily).
DEFAULT_SYNC_REMINDER_BY_BACKEND = {
    BACKEND_KMD: True,
    BACKEND_EFORSYNING: False,
    BACKEND_WATTSON: False,
}
