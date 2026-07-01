"""
SMS service using Africa's Talking.
Falls back to a logged mock if AT_API_KEY isn't set (local/dev use only).
"""
import logging
import africastalking
from app.config import get_settings

logger = logging.getLogger("kejaflix.sms")
settings = get_settings()

_initialized = False


def _get_sms_client():
    global _initialized
    if not _initialized:
        africastalking.initialize(settings.AT_USERNAME, settings.AT_API_KEY)
        _initialized = True
    return africastalking.SMS


def send_sms(phone: str, message: str) -> bool:
    if not settings.AT_API_KEY:
        logger.info("[SMS MOCK] to=%s message=%r", phone, message)
        return True

    try:
        sms = _get_sms_client()
        response = sms.send(message, [phone], sender_id=settings.AT_SENDER_ID)
        status = response["SMSMessageData"]["Recipients"][0]["status"]
        if status != "Success":
            logger.error("SMS send failed to=%s status=%s response=%s", phone, status, response)
        return status == "Success"
    except Exception:
        logger.exception("SMS send raised an exception to=%s", phone)
        return False
