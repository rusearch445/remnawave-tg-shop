import logging
import asyncio
from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy.orm import sessionmaker

from config.settings import Settings
from bot.middlewares.i18n import JsonI18n
from bot.keyboards.inline.user_keyboards import get_trial_expiry_buy_markup
from db.dal import subscription_dal

TRIAL_CHECK_INTERVAL_SECONDS = 600  # 10 minutes


async def _send_trial_expiry_notifications(
    bot: Bot,
    settings: Settings,
    i18n: JsonI18n,
    async_session_factory: sessionmaker,
):
    async with async_session_factory() as session:
        expiring_subs = await subscription_dal.get_trial_subscriptions_expiring_in_hours(
            session, hours=1.0
        )

        if not expiring_subs:
            return

        logging.info("Trial expiry check: found %d trial(s) expiring within 1 hour", len(expiring_subs))

        for sub in expiring_subs:
            user = sub.user
            if not user:
                continue

            lang = user.language_code or settings.DEFAULT_LANGUAGE
            first_name = user.first_name or f"User {user.user_id}"
            _ = lambda k, **kw: i18n.gettext(lang, k, **kw)

            markup = get_trial_expiry_buy_markup(lang, i18n)

            try:
                await bot.send_message(
                    user.user_id,
                    _("trial_expiring_1h_notification", user_name=first_name),
                    reply_markup=markup,
                )
                await subscription_dal.update_subscription_notification_time(
                    session, sub.subscription_id, datetime.now(timezone.utc)
                )
                await session.commit()
                logging.info(
                    "Sent trial expiry notification to user %d (sub %d)",
                    user.user_id, sub.subscription_id,
                )
            except Exception as e:
                logging.error(
                    "Failed to send trial expiry notification to user %d: %s",
                    user.user_id, e,
                )


async def trial_expiry_check_loop(
    bot: Bot,
    settings: Settings,
    i18n: JsonI18n,
    async_session_factory: sessionmaker,
):
    if not settings.TRIAL_ENABLED:
        logging.info("Trial is disabled, skipping trial expiry notification task")
        return

    logging.info("Trial expiry notification task started (interval: %ds)", TRIAL_CHECK_INTERVAL_SECONDS)

    while True:
        try:
            await _send_trial_expiry_notifications(bot, settings, i18n, async_session_factory)
        except asyncio.CancelledError:
            logging.info("Trial expiry notification task cancelled")
            break
        except Exception:
            logging.exception("Unexpected error in trial expiry check loop")

        await asyncio.sleep(TRIAL_CHECK_INTERVAL_SECONDS)
