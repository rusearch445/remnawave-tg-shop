import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from bot.middlewares.i18n import JsonI18n
from db.dal import partner_dal, user_dal

router = Router(name="user_partner_router")

MIN_WITHDRAWAL = 1000.0


class PartnerWithdrawalStates(StatesGroup):
    waiting_amount = State()
    waiting_requisites = State()
    waiting_confirm = State()


def _get_back_kb(lang: str, i18n: JsonI18n) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=i18n.gettext(lang, "back_to_main_menu_button"),
        callback_data="main_action:back_to_main",
    ))
    return builder.as_markup()


@router.callback_query(F.data == "main_action:partner_balance")
async def partner_balance_handler(
    callback: types.CallbackQuery,
    i18n_data: dict,
    settings: Settings,
    session: AsyncSession,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kw: i18n.gettext(current_lang, key, **kw)

    user = await user_dal.get_user_by_id(session, callback.from_user.id)
    if not user or not getattr(user, "is_partner", False):
        try:
            await callback.answer(_("error_occurred_try_again"), show_alert=True)
        except Exception:
            pass
        return

    balance = float(user.partner_balance or 0.0)
    percent = int(user.partner_commission_percent or 0)

    text = _("partner_balance_info", balance=round(balance, 2), percent=percent)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=_("partner_withdraw_button"),
        callback_data="partner:request_withdrawal",
    ))
    builder.row(InlineKeyboardButton(
        text=_("partner_history_button"),
        callback_data="partner:withdrawal_history",
    ))
    builder.row(InlineKeyboardButton(
        text=_("back_to_main_menu_button"),
        callback_data="main_action:back_to_main",
    ))

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data == "partner:request_withdrawal")
async def partner_request_withdrawal_handler(
    callback: types.CallbackQuery,
    i18n_data: dict,
    settings: Settings,
    session: AsyncSession,
    state: FSMContext,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kw: i18n.gettext(current_lang, key, **kw)

    user = await user_dal.get_user_by_id(session, callback.from_user.id)
    if not user or not getattr(user, "is_partner", False):
        await callback.answer(_("error_occurred_try_again"), show_alert=True)
        return

    balance = float(user.partner_balance or 0.0)
    if balance < MIN_WITHDRAWAL:
        try:
            await callback.answer(_("partner_balance_zero"), show_alert=True)
        except Exception:
            pass
        return

    await state.set_state(PartnerWithdrawalStates.waiting_amount)
    await state.update_data(lang=current_lang, balance=balance)

    try:
        await callback.message.edit_text(
            _("partner_enter_amount", balance=round(balance, 2)),
            reply_markup=_get_back_kb(current_lang, i18n),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            _("partner_enter_amount", balance=round(balance, 2)),
            reply_markup=_get_back_kb(current_lang, i18n),
            parse_mode="HTML",
        )
    try:
        await callback.answer()
    except Exception:
        pass


@router.message(PartnerWithdrawalStates.waiting_amount, F.text)
async def partner_withdrawal_amount_handler(
    message: types.Message,
    i18n_data: dict,
    settings: Settings,
    session: AsyncSession,
    state: FSMContext,
):
    data = await state.get_data()
    current_lang = data.get("lang") or i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kw: i18n.gettext(current_lang, key, **kw)
    balance = float(data.get("balance", 0.0))

    try:
        amount = float(message.text.replace(",", ".").strip())
    except (ValueError, TypeError):
        await message.answer(_("partner_amount_invalid"), parse_mode="HTML")
        return

    if amount < MIN_WITHDRAWAL:
        await message.answer(_("partner_amount_invalid"), parse_mode="HTML")
        return

    if amount > balance:
        await message.answer(_("partner_amount_exceeds_balance", balance=round(balance, 2)), parse_mode="HTML")
        return

    await state.update_data(amount=amount)
    await state.set_state(PartnerWithdrawalStates.waiting_requisites)
    await message.answer(_("partner_enter_requisites"), reply_markup=_get_back_kb(current_lang, i18n), parse_mode="HTML")


@router.message(PartnerWithdrawalStates.waiting_requisites, F.text)
async def partner_withdrawal_requisites_handler(
    message: types.Message,
    i18n_data: dict,
    settings: Settings,
    state: FSMContext,
):
    data = await state.get_data()
    current_lang = data.get("lang") or i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kw: i18n.gettext(current_lang, key, **kw)

    requisites = message.text.strip()
    if not requisites:
        await message.answer(_("error_try_again"))
        return

    amount = float(data.get("amount", 0.0))
    await state.update_data(requisites=requisites)
    await state.set_state(PartnerWithdrawalStates.waiting_confirm)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=_("partner_withdrawal_confirm_button"),
        callback_data="partner:withdrawal_confirm",
    ))
    builder.row(InlineKeyboardButton(
        text=_("partner_withdrawal_cancel_button"),
        callback_data="partner:withdrawal_cancel",
    ))

    await message.answer(
        _("partner_withdrawal_confirm", amount=round(amount, 2), requisites=requisites),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "partner:withdrawal_confirm")
async def partner_withdrawal_confirm_handler(
    callback: types.CallbackQuery,
    i18n_data: dict,
    settings: Settings,
    session: AsyncSession,
    state: FSMContext,
):
    data = await state.get_data()
    current_lang = data.get("lang") or i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kw: i18n.gettext(current_lang, key, **kw)

    amount = float(data.get("amount", 0.0))
    requisites = data.get("requisites", "")

    await state.clear()

    if not amount or not requisites:
        await callback.answer(_("error_try_again"), show_alert=True)
        return

    # Re-verify partner status and balance from DB (FSM data may be stale)
    user = await user_dal.get_user_by_id(session, callback.from_user.id)
    if not user or not getattr(user, "is_partner", False):
        await callback.answer(_("error_occurred_try_again"), show_alert=True)
        return

    if amount < MIN_WITHDRAWAL:
        await callback.answer(_("partner_amount_invalid"), show_alert=True)
        return

    live_balance = float(user.partner_balance or 0.0)
    if amount > live_balance:
        await callback.answer(
            _("partner_amount_exceeds_balance", balance=round(live_balance, 2)),
            show_alert=True,
        )
        return

    withdrawal = await partner_dal.create_withdrawal_request(session, callback.from_user.id, amount, requisites)
    if not withdrawal:
        await callback.answer(_("error_occurred_try_again"), show_alert=True)
        return

    await session.commit()

    try:
        await callback.message.edit_text(
            _("partner_withdrawal_submitted", amount=round(amount, 2)),
            reply_markup=_get_back_kb(current_lang, i18n),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            _("partner_withdrawal_submitted", amount=round(amount, 2)),
            reply_markup=_get_back_kb(current_lang, i18n),
            parse_mode="HTML",
        )
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data == "partner:withdrawal_cancel")
async def partner_withdrawal_cancel_handler(
    callback: types.CallbackQuery,
    i18n_data: dict,
    settings: Settings,
    state: FSMContext,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kw: i18n.gettext(current_lang, key, **kw)

    await state.clear()
    try:
        await callback.message.edit_text(
            _("error_try_again"),
            reply_markup=_get_back_kb(current_lang, i18n),
        )
    except Exception:
        pass
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data == "partner:withdrawal_history")
async def partner_withdrawal_history_handler(
    callback: types.CallbackQuery,
    i18n_data: dict,
    settings: Settings,
    session: AsyncSession,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kw: i18n.gettext(current_lang, key, **kw)

    withdrawals = await partner_dal.get_user_withdrawals(session, callback.from_user.id)

    if not withdrawals:
        text = _("partner_withdrawal_history_empty")
    else:
        status_map = {
            "pending": _("partner_withdrawal_status_pending"),
            "approved": _("partner_withdrawal_status_approved"),
            "rejected": _("partner_withdrawal_status_rejected"),
        }
        text = _("partner_withdrawal_history_header")
        for w in withdrawals:
            status_label = status_map.get(w.status, w.status)
            date_str = w.created_at.strftime("%d.%m.%Y") if w.created_at else "—"
            text += _("partner_withdrawal_history_item",
                      id=w.withdrawal_id,
                      amount=round(w.amount, 2),
                      status=status_label,
                      date=date_str)

    try:
        await callback.message.edit_text(text, reply_markup=_get_back_kb(current_lang, i18n), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=_get_back_kb(current_lang, i18n), parse_mode="HTML")
    try:
        await callback.answer()
    except Exception:
        pass
