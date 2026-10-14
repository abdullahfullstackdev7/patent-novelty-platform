"""Subscriptions: one active plan per client, changes happen on month boundaries.

`ended_on` is exclusive: a subscription that ends on 2026-09-01 is last billed for August. A plan
or seat change ends the current row and starts a new one on the same date, so every month has
exactly one active subscription per client and the MRR views stay simple.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Client, Plan, Subscription


class BillingError(ValueError):
    """A request that breaks a billing rule. The message is safe to show to the admin."""


def month_start(day: date) -> date:
    return day.replace(day=1)


def next_month(day: date) -> date:
    first = month_start(day)
    return date(first.year + (first.month == 12), first.month % 12 + 1, 1)


def previous_month(day: date) -> date:
    first = month_start(day)
    return date(first.year - (first.month == 1), (first.month - 2) % 12 + 1, 1)


def active_subscription(session: Session, client_id: uuid.UUID, on: date) -> Subscription | None:
    """The subscription active on `on` (started on or before it, not yet ended)."""
    return session.scalars(
        select(Subscription)
        .where(
            Subscription.client_id == client_id,
            Subscription.started_on <= on,
            (Subscription.ended_on.is_(None)) | (Subscription.ended_on > on),
        )
        .order_by(Subscription.started_on.desc())
        .limit(1)
    ).first()


def get_plan(session: Session, code: str) -> Plan:
    plan = session.scalar(select(Plan).where(Plan.code == code))
    if plan is None:
        raise BillingError(f"Unknown plan '{code}'")
    return plan


def change_subscription(
    session: Session,
    client_id: uuid.UUID,
    plan_code: str,
    seats: int | None,
    effective: date,
) -> Subscription:
    """Start (or switch to) a plan from the first day of `effective`'s month.

    Returns the new subscription, or the current one when nothing changes.
    """
    if session.get(Client, client_id) is None:
        raise BillingError("Client not found")
    plan = get_plan(session, plan_code)
    seat_count = seats if seats is not None else plan.seats
    if seat_count < 1:
        raise BillingError("A subscription needs at least one seat")
    start = month_start(effective)

    current = active_subscription(session, client_id, start)
    if current is not None:
        if current.plan_id == plan.id and current.seats == seat_count:
            return current
        if current.started_on >= start:
            raise BillingError(
                "A change cannot take effect before the current subscription started"
            )
        current.ended_on = start
        current.status = "cancelled"
    later = session.scalar(
        select(Subscription.id).where(
            Subscription.client_id == client_id, Subscription.started_on >= start
        )
    )
    if later is not None:
        raise BillingError("The client already has a subscription starting on or after that month")

    subscription = Subscription(
        client_id=client_id, plan_id=plan.id, status="active", seats=seat_count, started_on=start
    )
    session.add(subscription)
    session.flush()
    return subscription


def cancel_subscription(session: Session, client_id: uuid.UUID, effective: date) -> Subscription:
    """End the active subscription from the first day of the month after `effective`.

    Cancelling in August means August is still billed and September is not.
    """
    end = next_month(effective)
    current = active_subscription(session, client_id, effective)
    if current is None:
        raise BillingError("The client has no active subscription")
    if end <= current.started_on:
        raise BillingError("A subscription cannot end before it starts")
    current.ended_on = end
    current.status = "cancelled"
    session.flush()
    return current
