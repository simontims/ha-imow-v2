DOMAIN = "imow_v2"
MANUFACTURER = "STIHL"
DEFAULT_SCAN_INTERVAL = 10  # minutes
DEFAULT_TRACKING_INTERVAL = 60  # seconds between GPS fixes while away from the dock; 0 = off

# Azure B2C PKCE constants (accepted by STIHL B2C); the verifier/challenge pair
# is generated fresh for every login in auth.py
B2C_CLIENT_ID       = "0d947284-c186-454e-96fd-0094f4510b3f"
B2C_REDIRECT_URI    = "imow://www.imow.com/welcome/login"
B2C_POLICY          = "b2c_1a_production_flow_signin"
B2C_POLICY_MIXED    = "B2C_1A_production_Flow_SignIn"
B2C_BASE            = "https://login.stihl.com/stihlidproduction.onmicrosoft.com"
B2C_AUTHORIZE_URL   = f"{B2C_BASE}/{B2C_POLICY}/oauth2/v2.0/authorize"
B2C_TOKEN_URL       = f"{B2C_BASE}/{B2C_POLICY}/oauth2/v2.0/token"
B2C_SCOPE           = "offline_access https://login.stihl.com/scopes/profile openid"

# Endpoints as used by the myimow.stihl.com web app
APIM_KEY            = "52659909060946fc88f2d3368c16d9c7"
API_BASE            = "https://apim.stihl.cloud/imow/p"
API_MOWERS          = f"{API_BASE}/mowertwin/api/v1/mowers"
API_MOWER_SETTINGS  = f"{API_BASE}/mowertwin/api/v1/mower-settings/{{id}}"
API_MOWING_PLAN     = f"{API_BASE}/mowertwin/api/v1/mowing-plans/{{id}}"
API_EVENT_HISTORY   = f"{API_BASE}/api/v1/history/mower/{{id}}"
API_ADVICES         = f"{API_BASE}/api/v1/advices/{{id}}"
API_COMMAND         = f"{API_BASE}/mowerctrl/api/v1/mower-commands/{{id}}/{{cmd}}"
API_SIGNALR_NEG     = f"{API_BASE}/signalr/api/v1/negotiate?negotiateVersion=1"

# The myimow web app's translations; error texts are keys dB_errorDetails_{headline,description}_dtc_<6-digit code>
ERROR_TEXTS_URL     = "https://myimow.stihl.com/app-i18n-messages/{locale}.json"
ERROR_TEXT_LOCALES  = (
    "bg-BG", "cs-CZ", "da-DK", "de", "de-DE", "el-GR", "en-GB", "en-US", "es-ES", "es-US",
    "et-EE", "fi-FI", "fr-FR", "hr-HR", "hu-HU", "it-IT", "lt-LT", "lv-LV", "nb-NO", "nl-NL",
    "pl-PL", "pt-PT", "ro-RO", "ru-RU", "sk-SK", "sl-SI", "sr-Latn-RS", "sr-RS", "sv-SE", "uk-UA",
)

# Mower commands (POST mower-commands/{id}/{cmd})
CMD_START           = "start-mowing"
CMD_PAUSE           = "pause"
CMD_RESUME          = "resume"
CMD_DOCK            = "end-job-and-return-to-dock"
CMD_CLEAR_ERRORS    = "clear-errors"
CMD_FORCE_UPDATE    = "force-status-update"

# SignalR hub messages: target → where the partial JSON is merged
SIGNALR_STATUS      = "mowerStatus"    # merged into the mower object
SIGNALR_SETTINGS    = "mowerSettings"  # merged into mower["_settings"]
SIGNALR_PLAN        = "mowingPlan"     # merged into mower["_plan"]
SIGNALR_ADVICES     = "advices"        # replaces mower["_advices"]

# device.overallState.state → category, as grouped by the myimow web app
OVERALL_STATE_GROUPS = {
    "docked": {
        "docked", "dockedBatteryWithJob", "dockedNoJob", "dockedPrepareMowing",
        "dockedRainWithJob", "cleaningDockConnection", "waitLearningStartingPoints",
        "TeamSetupAtBase", "TeamSetupAtMain",
    },
    "charging": {"charging", "chargingBatteryWithJob", "chargingNoJob", "chargingRainWithJob"},
    "returning": {"drivingHome", "drivingHomeBattery", "drivingHomeMowplan", "drivingHomeRain"},
    "driving": {
        "drivingToZone", "learningStartingPoints", "completingLearningStartingPoints",
        "pausedOrIdlePrepareMowing",  # just left the dock, about to drive to the zone
    },
    "mowing": {"mowing"},
    "paused": {
        "pausedOrIdle", "parkedInSideArea",
        "parkedInSideAreaBattery", "parkedInSideAreaMowplan", "parkedInSideAreaRain",
    },
    "error": {"error", "invalid", "blockedLearningStartingPoints", "selfTesting", "stopped"},
    "locked": {"beingCarried", "locked", "outsideGeofence"},
    "offline": {"offline", "resettingSecretData"},
    "sleeping": {"sleeping"},
    "busy": {"internalWorkInProgress"},  # e.g. a few seconds after a start command
}

USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
