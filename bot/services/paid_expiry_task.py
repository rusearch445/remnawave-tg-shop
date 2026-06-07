import logging
import asyncio

from aiogram import Bot
from sqlalchemy.orm import sessionmaker

from config.settings import Settings
from bot.middlewares.i18n import JsonI18n
from bot.keyboards.inline.user_keyboards import get_paid_expiry_renew_markup
from bot.utils.text_sanitizer import safe_user_name
from db.dal import subscription_dal

PAID_CHECK_INTERVAL_SECONDS = 600  # 10 minutes

# (hours_before_expiry, flag_column_name, locale_key)
NOTIFICATION_LEVELS = [
    (24.0, "notified_1d_before", "paid_expiring_1d_notification"),
    (1.0, "notified_1h_before", "paid_expiring_1h_notification"),
]


async def _send_paid_expiry_notifications(
    bot: Bot,
    settings: Settings,
    i18n: JsonI18n,
    async_session_factory: sessionmaker,
):
    for hours, flag_name, locale_key in NOTIFICATION_LEVELS:
        async with async_session_factory() as session:
            expiring_subs = await subscription_dal.get_paid_subscriptions_expiring_for_notification(
                session, hours=hours, notified_flag=flag_name,
            )
            if not expiring_subs:
                continue

            logging.info(
                "Paid expiry check (%sh): found %d paid sub(s) to notify",
                hours, len(expiring_subs),
            )

            for sub in expiring_subs:
                user = sub.user
                if not user:
                    continue
                lang = user.language_code or settings.DEFAULT_LANGUAGE
                first_name = safe_user_name(user.first_name)
                _ = lambda k, **kw: i18n.gettext(lang, k, **kw)

                markup = get_paid_expiry_renew_markup(lang, i18n)

                try:
                    await bot.send_message(
                        user.user_id,
                        _(locale_key, user_name=first_name),
                        reply_markup=markup,
                    )
                    await subscription_dal.mark_subscription_notified(
                        session, sub.subscription_id, flag_name,
                    )
                    await session.commit()
                    logging.info(
                        "Sent paid expiry %sh notification to user %d (sub %d)",
                        hours, user.user_id, sub.subscription_id,
                    )
                except Exception as e:
                    logging.error(
                        "Failed to send paid expiry %sh notification to user %d: %s",
                        hours, user.user_id, e,
                    )


async def paid_expiry_check_loop(
    bot: Bot,
    settings: Settings,
    i18n: JsonI18n,
    async_session_factory: sessionmaker,
):
    logging.info(
        "Paid subscription expiry notification task started (interval: %ds)",
        PAID_CHECK_INTERVAL_SECONDS,
    )

    while True:
        try:
            await _send_paid_expiry_notifications(bot, settings, i18n, async_session_factory)
        except asyncio.CancelledError:
            logging.info("Paid expiry notification task cancelled")
            break
        except Exception:
            logging.exception("Unexpected error in paid expiry check loop")

        await asyncio.sleep(PAID_CHECK_INTERVAL_SECONDS)
