import logging
from typing import List, Optional
from datetime import datetime, timezone

from sqlalchemy import select, update, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User, PartnerWithdrawal


async def set_partner_status(
    session: AsyncSession,
    user_id: int,
    is_partner: bool,
    commission_percent: int = 0,
) -> Optional[User]:
    user = await session.get(User, user_id)
    if not user:
        return None
    user.is_partner = is_partner
    user.partner_commission_percent = commission_percent if is_partner else 0
    if not is_partner:
        pass  # keep balance intact on revoke
    session.add(user)
    return user


async def get_partner_balance(session: AsyncSession, user_id: int) -> float:
    user = await session.get(User, user_id)
    if not user:
        return 0.0
    return float(user.partner_balance or 0.0)


async def credit_partner_balance(
    session: AsyncSession, user_id: int, amount: float
) -> float:
    user = await session.get(User, user_id)
    if not user:
        logging.warning("credit_partner_balance: user %d not found", user_id)
        return 0.0
    current = float(user.partner_balance or 0.0)
    user.partner_balance = round(current + amount, 2)
    session.add(user)
    logging.info(
        "Partner balance credited: user %d +%.2f RUB (new balance: %.2f)",
        user_id, amount, user.partner_balance,
    )
    return user.partner_balance


async def deduct_partner_balance(
    session: AsyncSession, user_id: int, amount: float
) -> float:
    user = await session.get(User, user_id)
    if not user:
        logging.warning("deduct_partner_balance: user %d not found", user_id)
        return 0.0
    current = float(user.partner_balance or 0.0)
    user.partner_balance = round(max(0.0, current - amount), 2)
    session.add(user)
    return user.partner_balance


MIN_WITHDRAWAL_AMOUNT = 1000.0


async def create_withdrawal_request(
    session: AsyncSession,
    user_id: int,
    amount: float,
    requisites: str,
) -> Optional[PartnerWithdrawal]:
    user = await session.get(User, user_id)
    if not user or not user.is_partner:
        return None

    if amount < MIN_WITHDRAWAL_AMOUNT:
        logging.warning("create_withdrawal_request: amount %.2f below minimum", amount)
        return None

    balance = float(user.partner_balance or 0.0)

    # Sum all currently pending requests to prevent double-spend
    pending_sum_result = await session.execute(
        select(sa_func.coalesce(sa_func.sum(PartnerWithdrawal.amount), 0.0))
        .where(PartnerWithdrawal.user_id == user_id)
        .where(PartnerWithdrawal.status == "pending")
    )
    pending_sum = float(pending_sum_result.scalar() or 0.0)

    if amount + pending_sum > balance:
        logging.warning(
            "create_withdrawal_request: amount %.2f + pending %.2f exceeds balance %.2f for user %d",
            amount, pending_sum, balance, user_id,
        )
        return None

    withdrawal = PartnerWithdrawal(
        user_id=user_id,
        amount=amount,
        requisites=requisites,
        status="pending",
    )
    session.add(withdrawal)
    return withdrawal


async def get_pending_withdrawals(session: AsyncSession) -> List[PartnerWithdrawal]:
    result = await session.execute(
        select(PartnerWithdrawal)
        .where(PartnerWithdrawal.status == "pending")
        .order_by(PartnerWithdrawal.created_at.asc())
    )
    return list(result.scalars().all())


async def get_withdrawal_by_id(
    session: AsyncSession, withdrawal_id: int
) -> Optional[PartnerWithdrawal]:
    return await session.get(PartnerWithdrawal, withdrawal_id)


async def update_withdrawal_status(
    session: AsyncSession,
    withdrawal_id: int,
    status: str,
    admin_note: Optional[str] = None,
) -> Optional[PartnerWithdrawal]:
    withdrawal = await session.get(PartnerWithdrawal, withdrawal_id)
    if not withdrawal:
        return None
    withdrawal.status = status
    withdrawal.processed_at = datetime.now(timezone.utc)
    if admin_note is not None:
        withdrawal.admin_note = admin_note
    if status == "approved":
        await deduct_partner_balance(session, withdrawal.user_id, withdrawal.amount)
    session.add(withdrawal)
    return withdrawal


async def get_user_withdrawals(
    session: AsyncSession, user_id: int, limit: int = 10
) -> List[PartnerWithdrawal]:
    result = await session.execute(
        select(PartnerWithdrawal)
        .where(PartnerWithdrawal.user_id == user_id)
        .order_by(PartnerWithdrawal.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_all_partners(session: AsyncSession) -> List[User]:
    result = await session.execute(
        select(User).where(User.is_partner == True).order_by(User.user_id)
    )
    return list(result.scalars().all())
