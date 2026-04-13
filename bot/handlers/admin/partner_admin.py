import logging
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from bot.middlewares.i18n import JsonI18n
from db.dal import partner_dal, user_dal

router = Router(name="admin_partner_router")


class AdminPartnerStates(StatesGroup):
    waiting_grant_user_id = State()
    waiting_grant_percent = State()
    waiting_reject_reason = State()


def _back_kb(lang: str, i18n: JsonI18n) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=i18n.gettext(lang, "back_to_admin_panel_button"),
        callback_data="admin_action:main",
    ))
    return builder.as_markup()


def _partner_section_kb(lang: str, i18n: JsonI18n) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=i18n.gettext(lang, "admin_partner_grant_button"),
        callback_data="admin_partner:grant_prompt",
    ))
    builder.row(InlineKeyboardButton(
        text=i18n.gettext(lang, "admin_partner_withdrawals_button"),
        callback_data="admin_partner:withdrawals",
    ))
    builder.row(InlineKeyboardButton(
        text=i18n.gettext(lang, "back_to_admin_panel_button"),
        callback_data="admin_action:main",
    ))
    return builder.as_markup()


async def show_partner_section(
    callback: types.CallbackQuery,
    i18n_data: dict,
    settings: Settings,
    session: AsyncSession,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kw: i18n.gettext(current_lang, key, **kw)

    partners = await partner_dal.get_all_partners(session)
    pending = await partner_dal.get_pending_withdrawals(session)

    text = _("admin_partner_section_header", count=len(partners), pending=len(pending))

    if partners:
        text += "\n\n<b>Партнёры:</b>\n"
        for p in partners:
            uname = f"@{p.username}" if p.username else str(p.user_id)
            balance = round(float(p.partner_balance or 0), 2)
            text += f"• {uname} — {p.partner_commission_percent}% | баланс: {balance} ₽\n"

    try:
        await callback.message.edit_text(text, reply_markup=_partner_section_kb(current_lang, i18n), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=_partner_section_kb(current_lang, i18n), parse_mode="HTML")
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data == "admin_partner:grant_prompt")
async def admin_partner_grant_prompt(
    callback: types.CallbackQuery,
    i18n_data: dict,
    settings: Settings,
    state: FSMContext,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kw: i18n.gettext(current_lang, key, **kw)

    await state.set_state(AdminPartnerStates.waiting_grant_user_id)
    await state.update_data(lang=current_lang)

    try:
        await callback.message.edit_text(
            _("admin_partner_grant_prompt"),
            reply_markup=_back_kb(current_lang, i18n),
        )
    except Exception:
        await callback.message.answer(
            _("admin_partner_grant_prompt"),
            reply_markup=_back_kb(current_lang, i18n),
        )
    try:
        await callback.answer()
    except Exception:
        pass


@router.message(AdminPartnerStates.waiting_grant_user_id, F.text)
async def admin_partner_grant_user_id_handler(
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

    try:
        target_user_id = int(message.text.strip())
    except ValueError:
        await message.answer(_("admin_partner_grant_user_not_found"))
        return

    user = await user_dal.get_user_by_id(session, target_user_id)
    if not user:
        await message.answer(_("admin_partner_grant_user_not_found"))
        await state.clear()
        return

    await state.update_data(target_user_id=target_user_id)
    await state.set_state(AdminPartnerStates.waiting_grant_percent)

    await message.answer(
        _("admin_partner_grant_percent_prompt", user_id=target_user_id),
    )


@router.message(AdminPartnerStates.waiting_grant_percent, F.text)
async def admin_partner_grant_percent_handler(
    message: types.Message,
    i18n_data: dict,
    settings: Settings,
    session: AsyncSession,
    state: FSMContext,
    bot: Bot,
):
    data = await state.get_data()
    current_lang = data.get("lang") or i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kw: i18n.gettext(current_lang, key, **kw)
    target_user_id = data.get("target_user_id")

    try:
        percent = int(message.text.strip())
        if not (1 <= percent <= 50):
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите число от 1 до 50.")
        return

    await state.clear()

    await partner_dal.set_partner_status(session, target_user_id, True, percent)
    await session.commit()

    await message.answer(_("admin_partner_granted", user_id=target_user_id, percent=percent))

    try:
        await bot.send_message(
            target_user_id,
            f"🎉 <b>Вам присвоен статус партнёра!</b>\n\nКомиссия: <b>{percent}%</b> с каждой оплаты ваших рефералов.\n\nОткройте главное меню бота, чтобы увидеть раздел «Партнёрская программа».",
            parse_mode="HTML",
        )
    except Exception as e:
        logging.warning("Failed to notify new partner %d: %s", target_user_id, e)


@router.callback_query(F.data.startswith("admin_partner:revoke:"))
async def admin_partner_revoke_handler(
    callback: types.CallbackQuery,
    i18n_data: dict,
    settings: Settings,
    session: AsyncSession,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kw: i18n.gettext(current_lang, key, **kw)

    try:
        target_user_id = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        await callback.answer("Invalid user ID", show_alert=True)
        return

    await partner_dal.set_partner_status(session, target_user_id, False)
    await session.commit()

    await callback.answer(_("admin_partner_revoked", user_id=target_user_id), show_alert=True)
    await show_partner_section(callback, i18n_data, settings, session)


@router.callback_query(F.data == "admin_partner:withdrawals")
async def admin_partner_withdrawals_handler(
    callback: types.CallbackQuery,
    i18n_data: dict,
    settings: Settings,
    session: AsyncSession,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kw: i18n.gettext(current_lang, key, **kw)

    pending = await partner_dal.get_pending_withdrawals(session)

    if not pending:
        try:
            await callback.message.edit_text(
                _("admin_partner_withdrawals_empty"),
                reply_markup=_back_kb(current_lang, i18n),
            )
        except Exception:
            await callback.message.answer(
                _("admin_partner_withdrawals_empty"),
                reply_markup=_back_kb(current_lang, i18n),
            )
        try:
            await callback.answer()
        except Exception:
            pass
        return

    builder = InlineKeyboardBuilder()
    text = "💸 <b>Заявки на вывод:</b>\n\n"

    for w in pending:
        user = await user_dal.get_user_by_id(session, w.user_id)
        username = f"@{user.username}" if user and user.username else str(w.user_id)
        date_str = w.created_at.strftime("%d.%m.%Y %H:%M") if w.created_at else "—"
        text += _(
            "admin_partner_withdrawal_item",
            id=w.withdrawal_id,
            user_id=w.user_id,
            username=username,
            amount=round(w.amount, 2),
            requisites=w.requisites,
            date=date_str,
        )
        builder.row(InlineKeyboardButton(
            text=_("admin_partner_withdrawal_approve_button", id=w.withdrawal_id),
            callback_data=f"admin_partner:approve:{w.withdrawal_id}",
        ))
        builder.row(InlineKeyboardButton(
            text=_("admin_partner_withdrawal_reject_button", id=w.withdrawal_id),
            callback_data=f"admin_partner:reject:{w.withdrawal_id}",
        ))

    builder.row(InlineKeyboardButton(
        text=_("back_to_admin_panel_button"),
        callback_data="admin_action:main",
    ))

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("admin_partner:approve:"))
async def admin_partner_approve_handler(
    callback: types.CallbackQuery,
    i18n_data: dict,
    settings: Settings,
    session: AsyncSession,
    bot: Bot,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kw: i18n.gettext(current_lang, key, **kw)

    try:
        withdrawal_id = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        await callback.answer("Invalid ID", show_alert=True)
        return

    withdrawal = await partner_dal.update_withdrawal_status(session, withdrawal_id, "approved")
    if not withdrawal:
        await callback.answer("❌ Заявка не найдена.", show_alert=True)
        return

    await session.commit()
    await callback.answer(_("admin_partner_withdrawal_approved", id=withdrawal_id), show_alert=True)

    try:
        user = await user_dal.get_user_by_id(session, withdrawal.user_id)
        user_lang = user.language_code if user else settings.DEFAULT_LANGUAGE
        await bot.send_message(
            withdrawal.user_id,
            i18n.gettext(user_lang, "partner_withdrawal_approved", amount=round(withdrawal.amount, 2)),
            parse_mode="HTML",
        )
    except Exception as e:
        logging.warning("Failed to notify partner %d on approve: %s", withdrawal.user_id, e)

    await admin_partner_withdrawals_handler(callback, i18n_data, settings, session)


@router.callback_query(F.data.startswith("admin_partner:reject:"))
async def admin_partner_reject_prompt_handler(
    callback: types.CallbackQuery,
    i18n_data: dict,
    settings: Settings,
    state: FSMContext,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kw: i18n.gettext(current_lang, key, **kw)

    try:
        withdrawal_id = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        await callback.answer("Invalid ID", show_alert=True)
        return

    await state.set_state(AdminPartnerStates.waiting_reject_reason)
    await state.update_data(withdrawal_id=withdrawal_id, lang=current_lang)

    try:
        await callback.message.edit_text(
            _("admin_partner_withdrawal_reject_prompt", id=withdrawal_id),
            reply_markup=_back_kb(current_lang, i18n),
        )
    except Exception:
        await callback.message.answer(
            _("admin_partner_withdrawal_reject_prompt", id=withdrawal_id),
            reply_markup=_back_kb(current_lang, i18n),
        )
    try:
        await callback.answer()
    except Exception:
        pass


@router.message(AdminPartnerStates.waiting_reject_reason, F.text)
async def admin_partner_reject_reason_handler(
    message: types.Message,
    i18n_data: dict,
    settings: Settings,
    session: AsyncSession,
    state: FSMContext,
    bot: Bot,
):
    data = await state.get_data()
    current_lang = data.get("lang") or i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kw: i18n.gettext(current_lang, key, **kw)
    withdrawal_id = data.get("withdrawal_id")

    await state.clear()

    reason = message.text.strip()
    withdrawal = await partner_dal.update_withdrawal_status(session, withdrawal_id, "rejected", admin_note=reason)
    if not withdrawal:
        await message.answer("❌ Заявка не найдена.")
        return

    await session.commit()
    await message.answer(_("admin_partner_withdrawal_rejected", id=withdrawal_id))

    try:
        user = await user_dal.get_user_by_id(session, withdrawal.user_id)
        user_lang = user.language_code if user else settings.DEFAULT_LANGUAGE
        await bot.send_message(
            withdrawal.user_id,
            i18n.gettext(user_lang, "partner_withdrawal_rejected",
                         amount=round(withdrawal.amount, 2), note=reason),
            parse_mode="HTML",
        )
    except Exception as e:
        logging.warning("Failed to notify partner %d on reject: %s", withdrawal.user_id, e)
