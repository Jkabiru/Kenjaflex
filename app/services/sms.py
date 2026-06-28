"""
SMS service.

Production swap-in point: call Africa's Talking's /messaging endpoint here
using AT_USERNAME / AT_API_KEY from settings. Kept as a stub + log line so
the rest of the app (OTP delivery, rent reminders, vacancy notices) works
end-to-end in dev without real credentials.
"""
import logging

from app.config import get_settings

logger = logging.getLogger("kejaflix.sms")
settings = get_settings()


def send_sms(phone: str, message: str) -> bool:
    if not settings.AT_API_KEY:
        logger.info("[SMS MOCK] to=%s message=%r", phone, message)
        return True

    # Production implementation (Africa's Talking):
    #
    # import africastalking
    # africastalking.initialize(settings.AT_USERNAME, settings.AT_API_KEY)
    # sms = africastalking.SMS
    # response = sms.send(message, [phone], sender_id=settings.AT_SENDER_ID)
    # return response["SMSMessageData"]["Recipients"][0]["status"] == "Success"
    raise NotImplementedError("Wire up Africa's Talking SDK call here in production")
