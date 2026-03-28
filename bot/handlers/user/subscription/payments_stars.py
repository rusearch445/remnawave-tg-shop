import logging
from typing import Optional

from aiogram import F, Router, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.middlewares.i18n import JsonI18n
from bot.services.stars_service import StarsService
from config.settings import Settings

router = Router(name="user_subscription_payments_stars_router")


@router.callback_query(F.data.startswith("pay_stars:"))
async def pay_stars_callback_handler(
    callback: types.CallbackQuery,
    settings: Settings,
    i18n_data: dict,
    session: AsyncSession,
    stars_service: StarsService,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    get_text = (lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key)

    if not i18n or not callback.message:
        try:
            await callback.answer(get_text("error_occurred_try_again"), show_alert=True)
        except Exception:
            pass
        return

    if not settings.STARS_ENABLED:
        try:
            await callback.answer(get_text("payment_service_unavailable_alert"), show_alert=True)
        except Exception:
            pass
        return

    try:
        _, data_payload = callback.data.split(":", 1)
        parts = data_payload.split(":")
        months = float(parts[0])
        stars_price = int(float(parts[1]))
        sale_mode = parts[2] if len(parts) > 2 else "subscription"
        devices = int(parts[3]) if len(parts) > 3 else 1
    except (ValueError, IndexError):
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception:
            pass
        return

    user_id = callback.from_user.id
    human_value = str(int(months)) if float(months).is_integer() else f"{months:g}"
    if sale_mode == "extra_devices":
        payment_description = get_text("payment_description_extra_devices", count=devices)
    elif sale_mode == "traffic":
        payment_description = get_text("payment_description_traffic", traffic_gb=human_value)
    else:
        payment_description = get_text("payment_description_subscription", months=int(months))

    payment_db_id = await stars_service.create_invoice(
        session=session,
        user_id=user_id,
        months=months,
        stars_price=stars_price,
        description=payment_description,
        sale_mode=sale_mode,
        device_limit=devices,
    )

    if payment_db_id:
        if sale_mode == "extra_devices":
            stars_info_msg = get_text("payment_invoice_sent_message")
            stars_back_cb = "main_action:my_subscription"
        elif sale_mode == "traffic":
            stars_info_msg = get_text("payment_invoice_sent_message_traffic", traffic_gb=human_value)
            stars_back_cb = f"subscribe_period:{human_value}"
        else:
            stars_info_msg = get_text("payment_invoice_sent_message", months=int(months))
            stars_back_cb = f"subscribe_period:{human_value}"

        try:
            await callback.message.edit_text(
                stars_info_msg,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=get_text("back_to_payment_methods_button"),
                        callback_data=stars_back_cb,
                    )]
                ]),
            )
        except Exception as e_edit:
            logging.warning(f"Stars payment: failed to show invoice info message ({e_edit})")
        try:
            await callback.answer()
        except Exception:
            pass
        return

    try:
        await callback.answer(get_text("error_payment_gateway"), show_alert=True)
    except Exception:
        pass


@router.pre_checkout_query()
async def handle_pre_checkout_query(query: types.PreCheckoutQuery):
    try:
        await query.answer(ok=True)
    except Exception:
        # Nothing else to do here; Telegram will show an error if not answered
        pass


@router.message(F.successful_payment)
async def handle_successful_stars_payment(
    message: types.Message,
    settings: Settings,
    i18n_data: dict,
    session: AsyncSession,
    stars_service: StarsService,
):
    payload = (message.successful_payment.invoice_payload
               if message and message.successful_payment else "")
    try:
        parts = (payload or "").split(":")
        payment_db_id = int(parts[0])
        months = float(parts[1]) if len(parts) > 1 else 0
        sale_mode = parts[2] if len(parts) > 2 else "subscription"
    except Exception:
        return

    stars_amount = int(message.successful_payment.total_amount) if message.successful_payment else 0
    await stars_service.process_successful_payment(
        session=session,
        message=message,
        payment_db_id=payment_db_id,
        months=months,
        stars_amount=stars_amount,
        i18n_data=i18n_data,
        sale_mode=sale_mode,
    )
