from enum import Enum

class TriggerType(Enum):
    MORNING_OPEN  = "morning_open"
    US_OPEN       = "us_open"
    FOMC          = "fomc"
    NEWS_FLASH    = "news_flash"
    MARKET_ALERT  = "market_alert"
    MANUAL        = "manual"
