"""
Utility functions for sending messages with optional logo image.
"""
import logging
from pathlib import Path
from typing import Optional, Union

from aiogram import types, Bot
from aiogram.types import FSInputFile, InlineKeyboardMarkup

from config.settings import Settings


def resolve_logo_input(logo: Optional[str]):
    """
    Resolve MAIN_MENU_LOGO into a sendable photo value for aiogram.
    Supports:
      - local file path inside container -> FSInputFile
      - http(s) URL -> str
      - Telegram file_id -> str (fallback)
    """
    raw = (logo or "").strip()
    if not raw:
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    try:
        p = Path(raw)
        if p.exists() and p.is_file():
            return FSInputFile(str(p))
    except Exception:
        pass
    return raw


async def send_or_edit_message(
    event: Union[types.Message, types.CallbackQuery],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    settings: Optional[Settings] = None,
    is_edit: bool = False,
    parse_mode: Optional[str] = None,
    disable_web_page_preview: bool = False,
):
    """
    Universal function to send or edit a message with optional logo image.
    
    If MAIN_MENU_LOGO is configured in settings, sends/edits a photo message.
    Otherwise, sends/edits a text message.
    
    Args:
        event: Message or CallbackQuery event
        text: Message text (or caption for photo)
        reply_markup: Optional inline keyboard
        settings: Settings instance (to get MAIN_MENU_LOGO)
        is_edit: Whether to edit existing message or send new
        parse_mode: Parse mode for text (HTML, Markdown, etc.)
        disable_web_page_preview: Disable link preview for text messages
    """
    logo_value = None
    if settings:
        logo_value = resolve_logo_input(getattr(settings, "MAIN_MENU_LOGO", None))
    
    # Determine target message object
    target_message_obj: Optional[types.Message] = None
    if isinstance(event, types.Message):
        target_message_obj = event
    elif isinstance(event, types.CallbackQuery) and event.message:
        target_message_obj = event.message
    
    if not target_message_obj:
        logging.error(f"send_or_edit_message: target_message_obj is None")
        if isinstance(event, types.CallbackQuery):
            try:
                await event.answer("Error displaying message", show_alert=True)
            except Exception:
                pass
        return
    
    try:
        if logo_value:
            # Photo-based message
            if is_edit and getattr(target_message_obj, "photo", None):
                # Already a photo message -> update caption/markup
                await target_message_obj.edit_caption(
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
            else:
                # Can't convert text->photo in-place; send new message
                if is_edit:
                    try:
                        await target_message_obj.delete()
                    except Exception:
                        pass
                await target_message_obj.answer_photo(
                    photo=logo_value,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
        else:
            # Text-only message
            if is_edit and getattr(target_message_obj, "photo", None):
                # Editing a photo message without logo - edit caption
                await target_message_obj.edit_caption(
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
            elif is_edit:
                await target_message_obj.edit_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                    disable_web_page_preview=disable_web_page_preview,
                )
            else:
                await target_message_obj.answer(
                    text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                    disable_web_page_preview=disable_web_page_preview,
                )
        
        # Answer callback if needed
        if isinstance(event, types.CallbackQuery):
            try:
                await event.answer()
            except Exception:
                pass
                
    except Exception as e_send_edit:
        logging.warning(
            f"Failed to send/edit message (is_edit: {is_edit}): {type(e_send_edit).__name__} - {e_send_edit}"
        )
        # Fallback: try sending new message
        if is_edit and target_message_obj:
            try:
                if logo_value:
                    await target_message_obj.answer_photo(
                        photo=logo_value,
                        caption=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
                else:
                    await target_message_obj.answer(
                        text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                        disable_web_page_preview=disable_web_page_preview,
                    )
            except Exception as e_fallback:
                logging.error(f"Fallback send also failed: {e_fallback}")
        
        if isinstance(event, types.CallbackQuery):
            try:
                await event.answer()
            except Exception:
                pass

