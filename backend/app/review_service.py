"""Party-authorized, immutable double-blind reviews; never modifies money."""

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app import business_time
from app.auth_service import AccessContext
from app.booking_queries import _party
from app.errors import ApiError
from app.models import Listing, Reservation, User
from app.notification_service import notify
from app.review_models import Review, ReviewWindow
from app.review_schemas import (
    CATEGORIES,
    HostReviews,
    ListingReviews,
    PartyReviews,
    ReviewInput,
    ReviewOutput,
)

WINDOW = timedelta(days=14)
REMINDER = timedelta(hours=48)


def _locked_party(db: Session, actor: AccessContext, rid: UUID) -> Reservation:
    row = _party(db, actor, rid)
    locked = db.scalar(
        select(Reservation)
        .where(Reservation.id == row.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert locked is not None
    row = locked
    if row.guest_id == row.host_id:
        raise ApiError(
            403, "review_ineligible", "You cannot review your own reservation."
        )
    return row


def _role(row: Reservation, actor: AccessContext) -> Literal["guest", "host"]:
    return "guest" if row.guest_id == actor.user_id else "host"


def _reviews(db: Session, rid: UUID) -> list[Review]:
    return list(
        db.scalars(
            select(Review)
            .where(Review.reservation_id == rid)
            .order_by(Review.author_role)
        )
    )


def _output(db: Session, review: Review) -> ReviewOutput:
    user = db.get(User, review.author_id)
    return ReviewOutput(
        id=review.id,
        author_role=cast(Literal["guest", "host"], review.author_role),
        author_name=user.name if user else "StayHub member",
        text=review.text,
        overall=review.overall,
        categories=review.categories,
        submitted_at=review.submitted_at,
        published_at=review.published_at,
    )


def _status(
    db: Session, row: Reservation, actor: AccessContext, now: datetime
) -> PartyReviews:
    own, counterpart = None, None
    for review in _reviews(db, row.id):
        if review.author_id == actor.user_id:
            own = review
        elif review.published_at is not None:
            counterpart = review
    deadline = row.completed_at + WINDOW if row.completed_at is not None else None
    completed = row.state == "completed" and deadline is not None
    open_window = completed and now < cast(datetime, deadline)
    published = (
        own is not None and own.published_at is not None
    ) or counterpart is not None
    status: Literal["not_completed", "open", "submitted", "published", "closed"] = (
        "not_completed"
    )
    if completed:
        status = (
            "published"
            if published
            else "submitted"
            if own
            else "open"
            if open_window
            else "closed"
        )
    return PartyReviews(
        reservation_id=row.id,
        listing_title=str(row.listing_snapshot["title"]),
        role=_role(row, actor),
        eligible=bool(open_window and own is None),
        deadline=deadline,
        own=_output(db, own) if own else None,
        counterpart=_output(db, counterpart) if counterpart else None,
        status=status,
    )


def party_reviews(db: Session, actor: AccessContext, rid: UUID) -> PartyReviews:
    with db.begin():
        row = _party(db, actor, rid)
        if row.guest_id == row.host_id:
            raise ApiError(
                403, "review_ineligible", "You cannot review your own reservation."
            )
        return _status(db, row, actor, business_time.at(db))


def _window(db: Session, row: Reservation) -> ReviewWindow:
    assert row.completed_at is not None
    window = db.get(ReviewWindow, row.id)
    if window is None:
        window = ReviewWindow(reservation_id=row.id, deadline=row.completed_at + WINDOW)
        db.add(window)
        db.flush()
    return window


def completed(db: Session, row: Reservation, now: datetime) -> None:
    """Called with the reservation locked, in the completion source transaction."""
    if row.state != "completed" or row.completed_at is None:
        return
    window = _window(db, row)
    if window.eligibility_sent_at is not None:
        return
    submitted = {review.author_id for review in _reviews(db, row.id)}
    if now < window.deadline and row.guest_id != row.host_id:
        for recipient in (row.guest_id, row.host_id):
            if recipient not in submitted:
                notify(
                    db,
                    recipient,
                    "review_eligibility",
                    str(row.id),
                    title="Your completed stay is ready to review",
                    href=f"/trips/{row.id}/review",
                )
    window.eligibility_sent_at = now


def _publish(
    db: Session,
    row: Reservation,
    window: ReviewWindow,
    reviews: list[Review],
    now: datetime,
    actor_id: UUID | None = None,
) -> None:
    for review in reviews:
        if review.published_at is None:
            review.published_at = now
    if reviews:
        for recipient in (row.guest_id, row.host_id):
            notify(
                db,
                recipient,
                "review_publication",
                str(row.id),
                title="Reservation reviews are published",
                href=f"/trips/{row.id}/review",
                actor_id=actor_id,
            )
    window.closed_at = now
    window.reminder_sent_at = window.reminder_sent_at or now
    db.flush()


def submit(
    db: Session,
    actor: AccessContext,
    rid: UUID,
    body: ReviewInput,
    *,
    guard: Callable[[], None] | None = None,
) -> PartyReviews:
    with db.begin():
        row = _locked_party(db, actor, rid)
        if guard:
            guard()
        now = business_time.at(db)
        if row.state != "completed" or row.completed_at is None:
            raise ApiError(
                409, "review_ineligible", "Only completed stays can be reviewed."
            )
        if now >= row.completed_at + WINDOW:
            raise ApiError(
                409, "review_window_closed", "The 14-day review window has closed."
            )
        reviews = _reviews(db, row.id)
        if any(r.author_id == actor.user_id for r in reviews):
            raise ApiError(409, "review_exists", "Your submitted review is immutable.")
        role = _role(row, actor)
        if role == "guest" and (
            body.overall is None or set(body.categories) != set(CATEGORIES)
        ):
            raise ApiError(
                422,
                "validation_error",
                "Rate the stay overall and every category from 1 to 5.",
                field_errors={
                    "categories": "Rate every category.",
                    "overall": "Select an overall rating.",
                },
            )
        if role == "host" and (body.overall is not None or body.categories):
            raise ApiError(
                422,
                "validation_error",
                "Host reviews describe the guest and do not rate the listing.",
            )
        review = Review(
            reservation_id=row.id,
            listing_id=row.listing_id,
            author_id=actor.user_id,
            author_role=role,
            text=body.text,
            overall=body.overall,
            categories=body.categories,
            submitted_at=now,
        )
        db.add(review)
        db.flush()
        reviews.append(review)
        window = _window(db, row)
        if len(reviews) == 2:
            _publish(db, row, window, reviews, now, actor.user_id)
        result = _status(db, row, actor, now)
    return result


def aggregate_ratings(
    db: Session, listing_ids: Iterable[UUID]
) -> dict[UUID, tuple[float, int]]:
    ids = list(listing_ids)
    if not ids:
        return {}
    rows = db.execute(
        select(Review.listing_id, func.avg(Review.overall), func.count(Review.id))
        .where(
            Review.listing_id.in_(ids),
            Review.author_role == "guest",
            Review.published_at.is_not(None),
        )
        .group_by(Review.listing_id)
    )
    return {lid: (round(float(average), 2), count) for lid, average, count in rows}


def listing_reviews(
    db: Session, listing_id: UUID, limit: int = 20, cursor: UUID | None = None
) -> ListingReviews:
    with db.begin():
        if (
            db.scalar(
                select(Listing.id).where(
                    Listing.id == listing_id, Listing.status == "published"
                )
            )
            is None
        ):
            raise ApiError(404, "not_found", "This stay could not be found.")
        query = (
            select(Review)
            .where(
                Review.listing_id == listing_id,
                Review.author_role == "guest",
                Review.published_at.is_not(None),
            )
            .order_by(Review.id)
            .limit(limit + 1)
        )
        if cursor:
            query = query.where(Review.id > cursor)
        reviews = list(db.scalars(query))
        aggregate = aggregate_ratings(db, [listing_id]).get(listing_id)
        return ListingReviews(
            items=[_output(db, r) for r in reviews[:limit]],
            average=aggregate[0] if aggregate else None,
            count=aggregate[1] if aggregate else 0,
            next_cursor=str(reviews[limit - 1].id) if len(reviews) > limit else None,
        )


def sweep_reviews(db: Session, batch_size: int = 100) -> bool:
    """Run with an idle session. Each reservation owns one committed sweep unit."""
    with db.begin():
        now = business_time.at(db)
        due = or_(
            ReviewWindow.reservation_id.is_(None),
            and_(
                ReviewWindow.eligibility_sent_at.is_(None),
                ReviewWindow.closed_at.is_(None),
            ),
            and_(
                ReviewWindow.reminder_sent_at.is_(None),
                ReviewWindow.closed_at.is_(None),
                ReviewWindow.deadline <= now + REMINDER,
            ),
            and_(ReviewWindow.closed_at.is_(None), ReviewWindow.deadline <= now),
        )
        candidates = list(
            db.scalars(
                select(Reservation.id)
                .outerjoin(ReviewWindow, ReviewWindow.reservation_id == Reservation.id)
                .where(
                    Reservation.state == "completed",
                    Reservation.completed_at.is_not(None),
                    due,
                )
                .order_by(Reservation.id)
                .limit(batch_size + 1)
            )
        )
    for rid in candidates[:batch_size]:
        with db.begin():
            row = db.scalar(
                select(Reservation)
                .where(Reservation.id == rid)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None or row.state != "completed" or row.completed_at is None:
                continue
            now = business_time.at(db)
            window = _window(db, row)
            reviews = _reviews(db, rid)
            if window.closed_at is not None:
                continue
            submitted = {review.author_id for review in reviews}
            completed(db, row, now)
            if len(reviews) == 2 or now >= window.deadline:
                _publish(db, row, window, reviews, now)
            elif now >= window.deadline - REMINDER and window.reminder_sent_at is None:
                for recipient in (row.guest_id, row.host_id):
                    if recipient not in submitted:
                        notify(
                            db,
                            recipient,
                            "review_reminder",
                            str(rid),
                            title="Your review window closes within 48 hours",
                            href=f"/trips/{rid}/review",
                        )
                window.reminder_sent_at = now
    return len(candidates) > batch_size


def host_reviews(
    db: Session, actor: AccessContext, limit: int = 20, cursor: UUID | None = None
) -> "HostReviews":
    from app.auth_service import current_user
    from app.review_schemas import HostReviewOutput

    with db.begin():
        current_user(db, actor, "host")
        criteria = (
            Listing.owner_id == actor.user_id,
            Review.author_role == "guest",
            Review.published_at.is_not(None),
        )
        count, average = db.execute(
            select(func.count(Review.id), func.avg(Review.overall))
            .join(Listing, Listing.id == Review.listing_id)
            .where(*criteria)
        ).one()
        query = (
            select(Review, Listing.title)
            .join(Listing, Listing.id == Review.listing_id)
            .where(*criteria)
            .order_by(Review.id.desc())
            .limit(limit + 1)
        )
        if cursor:
            query = query.where(Review.id < cursor)
        rows = list(db.execute(query))
        return HostReviews(
            items=[
                HostReviewOutput(
                    **_output(db, review).model_dump(),
                    listing_id=review.listing_id,
                    listing_title=title,
                )
                for review, title in rows[:limit]
            ],
            average=round(float(average), 2) if average is not None else None,
            count=count,
            next_cursor=str(rows[limit - 1][0].id) if len(rows) > limit else None,
        )
