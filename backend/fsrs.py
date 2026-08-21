"""
FSRS-5 (Free Spaced Repetition Scheduler) - Pure Python Implementation

Implements the FSRS-5 algorithm based on parameters trained on 700M+ reviews.
No external dependencies beyond Python's standard library.

References:
- https://github.com/open-spaced-repetition/fsrs4anki
- FSRS-5 paper and parameter optimization results

Card States:
    0 = New
    1 = Learning
    2 = Review
    3 = Relearning

Rating Scale:
    1 = Again (complete failure)
    2 = Hard (recalled with significant difficulty)
    3 = Good (recalled with some effort)
    4 = Easy (recalled effortlessly)
"""

import math
from datetime import datetime, timedelta

# FSRS-5 default weights trained on 700M+ reviews
W = [
    0.4072,   # w[0]  - Initial stability for Again
    1.1829,   # w[1]  - Initial stability for Hard
    3.1262,   # w[2]  - Initial stability for Good
    15.4722,  # w[3]  - Initial stability for Easy
    7.2102,   # w[4]  - Initial difficulty baseline
    0.5316,   # w[5]  - Initial difficulty rating scaling
    1.0651,   # w[6]  - (unused in FSRS-5 core, reserved)
    0.0589,   # w[7]  - Difficulty mean reversion weight
    1.5330,   # w[8]  - Stability increase base factor
    0.1544,   # w[9]  - Stability penalty for high S
    1.0175,   # w[10] - Stability boost for low retrievability
    1.8294,   # w[11] - Failure stability base
    0.0953,   # w[12] - Failure difficulty penalty
    0.2975,   # w[13] - Failure stability from prior S
    2.2042,   # w[14] - Failure retrievability factor
    0.2407,   # w[15] - Hard penalty
    2.9466,   # w[16] - Easy bonus
    0.5034,   # w[17] - Short-term stability (hard)
    0.6567,   # w[18] - Short-term stability (good)
]

# Card states
STATE_NEW = 0
STATE_LEARNING = 1
STATE_REVIEW = 2
STATE_RELEARNING = 3

# Ratings
RATING_AGAIN = 1
RATING_HARD = 2
RATING_GOOD = 3
RATING_EASY = 4


class FSRSCard:
    """Represents a flashcard's current FSRS scheduling state.

    Attributes:
        stability: Memory stability in days (expected half-life at R=0.9).
        difficulty: Card difficulty on a 1-10 scale.
        state: Current card state (0=New, 1=Learning, 2=Review, 3=Relearning).
        last_review: ISO format date string of the last review.
        reps: Total number of reviews performed on this card.
    """

    def __init__(
        self,
        stability: float = 0.0,
        difficulty: float = 0.0,
        state: int = STATE_NEW,
        last_review: str = '',
        reps: int = 0,
    ):
        self.stability = stability
        self.difficulty = difficulty
        self.state = state
        self.last_review = last_review
        self.reps = reps

    def __repr__(self) -> str:
        return (
            f"FSRSCard(stability={self.stability:.4f}, difficulty={self.difficulty:.4f}, "
            f"state={self.state}, last_review='{self.last_review}', reps={self.reps})"
        )


class FSRSOutput:
    """Result of processing a review through the FSRS algorithm.

    Attributes:
        stability: Updated memory stability in days.
        difficulty: Updated difficulty (1-10 scale).
        state: New card state after this review.
        interval: Days until next scheduled review.
        next_review: ISO format date string for the next review.
        retrievability: Probability of recall at the time of this review.
    """

    def __init__(
        self,
        stability: float,
        difficulty: float,
        state: int,
        interval: int,
        next_review: str,
        retrievability: float,
    ):
        self.stability = stability
        self.difficulty = difficulty
        self.state = state
        self.interval = interval
        self.next_review = next_review
        self.retrievability = retrievability

    def __repr__(self) -> str:
        return (
            f"FSRSOutput(stability={self.stability:.4f}, difficulty={self.difficulty:.4f}, "
            f"state={self.state}, interval={self.interval}, "
            f"next_review='{self.next_review}', retrievability={self.retrievability:.4f})"
        )


def _clamp_difficulty(d: float) -> float:
    """Clamp difficulty to valid range [1, 10]."""
    return max(1.0, min(10.0, d))


def _clamp_stability(s: float) -> float:
    """Enforce minimum stability of 0.01 days."""
    return max(0.01, s)


def _initial_stability(rating: int) -> float:
    """Calculate initial stability S0 for a new card based on first rating.

    S0(G) = w[G-1] where G is the rating (1-4).

    Args:
        rating: FSRS rating (1=Again, 2=Hard, 3=Good, 4=Easy).

    Returns:
        Initial stability in days.
    """
    return W[rating - 1]


def _initial_difficulty(rating: int) -> float:
    """Calculate initial difficulty D0 for a new card.

    D0(G) = w[4] - exp(w[5] * (G - 1)) + 1

    Args:
        rating: FSRS rating (1=Again, 2=Hard, 3=Good, 4=Easy).

    Returns:
        Initial difficulty clamped to [1, 10].
    """
    d = W[4] - math.exp(W[5] * (rating - 1)) + 1
    return _clamp_difficulty(d)


def _retrievability(elapsed_days: float, stability: float) -> float:
    """Calculate the probability of recall (retrievability).

    R(t, S) = (1 + t / (9 * S))^(-1)

    Args:
        elapsed_days: Days since last review.
        stability: Current memory stability in days.

    Returns:
        Retrievability as a probability [0, 1].
    """
    if stability <= 0:
        return 0.0
    return (1.0 + elapsed_days / (9.0 * stability)) ** (-1)


def _next_interval(stability: float, desired_retention: float) -> int:
    """Calculate the next review interval in days.

    I = S * 9 * (1/desired_retention - 1)

    Args:
        stability: Memory stability in days.
        desired_retention: Target probability of recall (default 0.9).

    Returns:
        Interval in days (minimum 1).
    """
    if desired_retention <= 0 or desired_retention >= 1:
        desired_retention = 0.9
    interval = stability * 9.0 * (1.0 / desired_retention - 1.0)
    return max(1, round(interval))


def _update_difficulty(old_d: float, rating: int) -> float:
    """Update difficulty using mean reversion formula.

    D' = w[7] * D0(G) + (1 - w[7]) * D

    Args:
        old_d: Previous difficulty value.
        rating: Current review rating (1-4).

    Returns:
        Updated difficulty clamped to [1, 10].
    """
    d0 = _initial_difficulty(rating)
    new_d = W[7] * d0 + (1.0 - W[7]) * old_d
    return _clamp_difficulty(new_d)


def _stability_after_success(
    stability: float, difficulty: float, retrievability: float, rating: int
) -> float:
    """Calculate new stability after a successful recall (rating >= 2).

    S'_r = S * (exp(w[8]) * (11 - D) * S^(-w[9]) * (exp(w[10] * (1 - R)) - 1) + 1)

    With additional modifiers:
    - Hard penalty: multiply by w[15]
    - Easy bonus: multiply by w[16]

    Args:
        stability: Current stability.
        difficulty: Current difficulty.
        retrievability: Current retrievability at time of review.
        rating: Review rating (2=Hard, 3=Good, 4=Easy).

    Returns:
        New stability value (minimum 0.01).
    """
    s_base = stability * (
        math.exp(W[8])
        * (11.0 - difficulty)
        * (stability ** (-W[9]))
        * (math.exp(W[10] * (1.0 - retrievability)) - 1.0)
        + 1.0
    )

    # Apply hard/easy modifiers
    if rating == RATING_HARD:
        s_base *= W[15]
    elif rating == RATING_EASY:
        s_base *= W[16]

    return _clamp_stability(s_base)


def _stability_after_failure(
    stability: float, difficulty: float, retrievability: float
) -> float:
    """Calculate new stability after a failed recall (rating = 1/Again).

    S'_f = w[11] * D^(-w[12]) * ((S + 1)^w[13] - 1) * exp(w[14] * (1 - R))

    Args:
        stability: Current stability.
        difficulty: Current difficulty.
        retrievability: Retrievability at time of failure.

    Returns:
        New stability value (minimum 0.01).
    """
    s_new = (
        W[11]
        * (difficulty ** (-W[12]))
        * ((stability + 1.0) ** W[13] - 1.0)
        * math.exp(W[14] * (1.0 - retrievability))
    )
    return _clamp_stability(s_new)


def review_card(
    card: FSRSCard,
    rating: int,
    desired_retention: float = 0.9,
    review_date: str = None,
) -> FSRSOutput:
    """Process a review and return updated card state with the next interval.

    Handles all card state transitions:
    - New -> Learning (Again) or Review (Hard/Good/Easy)
    - Learning -> Learning (Again) or Review (Hard/Good/Easy)
    - Review -> Relearning (Again) or Review (Hard/Good/Easy)
    - Relearning -> Relearning (Again) or Review (Hard/Good/Easy)

    Args:
        card: Current card state (FSRSCard instance).
        rating: Review quality (1=Again, 2=Hard, 3=Good, 4=Easy).
        desired_retention: Target probability of recall for scheduling (0-1).
            Defaults to 0.9 (90% target retention).
        review_date: ISO format date string (YYYY-MM-DD) for this review.
            Defaults to today if not provided.

    Returns:
        FSRSOutput with updated scheduling parameters.

    Raises:
        ValueError: If rating is not in range [1, 4].
    """
    if rating < 1 or rating > 4:
        raise ValueError(f"Rating must be between 1 and 4, got {rating}")

    # Determine review date
    if review_date is None:
        today = datetime.now().date()
    else:
        today = datetime.fromisoformat(review_date).date()

    # Calculate elapsed days since last review
    if card.last_review:
        last = datetime.fromisoformat(card.last_review).date()
        elapsed_days = max(0, (today - last).days)
    else:
        elapsed_days = 0

    # --- Handle NEW cards (first review) ---
    if card.state == STATE_NEW:
        new_stability = _clamp_stability(_initial_stability(rating))
        new_difficulty = _initial_difficulty(rating)

        if rating == RATING_AGAIN:
            # Card enters Learning state with short interval
            new_state = STATE_LEARNING
            interval = 1  # 1 day (represents short-term relearning)
        else:
            # Card graduates directly to Review
            new_state = STATE_REVIEW
            interval = _next_interval(new_stability, desired_retention)

    # --- Handle LEARNING / RELEARNING cards ---
    elif card.state in (STATE_LEARNING, STATE_RELEARNING):
        if rating == RATING_AGAIN:
            # Stay in learning/relearning with short interval
            new_state = STATE_LEARNING if card.state == STATE_LEARNING else STATE_RELEARNING
            # Use initial stability for Again to keep it short
            new_stability = _clamp_stability(_initial_stability(RATING_AGAIN))
            new_difficulty = _update_difficulty(card.difficulty, rating) if card.difficulty > 0 else _initial_difficulty(rating)
            interval = 1
        else:
            # Graduate to Review state
            new_state = STATE_REVIEW
            if card.stability > 0 and elapsed_days > 0:
                r = _retrievability(elapsed_days, card.stability)
                new_stability = _stability_after_success(card.stability, card.difficulty, r, rating)
            else:
                # First graduation: use initial stability based on rating
                new_stability = _clamp_stability(_initial_stability(rating))
            new_difficulty = _update_difficulty(card.difficulty, rating) if card.difficulty > 0 else _initial_difficulty(rating)
            interval = _next_interval(new_stability, desired_retention)

    # --- Handle REVIEW cards ---
    else:  # STATE_REVIEW
        r = _retrievability(elapsed_days, card.stability) if card.stability > 0 else 0.0

        new_difficulty = _update_difficulty(card.difficulty, rating)

        if rating == RATING_AGAIN:
            # Failed recall -> Relearning
            new_state = STATE_RELEARNING
            new_stability = _stability_after_failure(card.stability, card.difficulty, r)
            interval = 1  # Short relearning interval
        else:
            # Successful recall -> stays in Review
            new_state = STATE_REVIEW
            new_stability = _stability_after_success(card.stability, card.difficulty, r, rating)
            interval = _next_interval(new_stability, desired_retention)

    # Ensure minimum constraints
    new_stability = _clamp_stability(new_stability)
    new_difficulty = _clamp_difficulty(new_difficulty)
    interval = max(1, interval)

    # Calculate next review date
    next_review_date = today + timedelta(days=interval)

    # Calculate retrievability at this review moment
    if card.stability > 0 and elapsed_days > 0:
        current_retrievability = _retrievability(elapsed_days, card.stability)
    else:
        current_retrievability = 1.0  # New card or same-day review

    return FSRSOutput(
        stability=new_stability,
        difficulty=new_difficulty,
        state=new_state,
        interval=interval,
        next_review=next_review_date.isoformat(),
        retrievability=current_retrievability,
    )


def sm2_to_fsrs_rating(quality: int) -> int:
    """Convert SM-2 quality score (0-5) to FSRS rating (1-4).

    SM-2 quality mapping:
        0 (complete blackout)     -> 1 (Again)
        1 (incorrect, remembered) -> 1 (Again)
        2 (incorrect, easy recall)-> 2 (Hard)
        3 (correct, difficult)    -> 2 (Hard)
        4 (correct, hesitation)   -> 3 (Good)
        5 (correct, perfect)      -> 4 (Easy)

    Args:
        quality: SM-2 quality score in range [0, 5].

    Returns:
        FSRS rating in range [1, 4].

    Raises:
        ValueError: If quality is not in range [0, 5].
    """
    if quality < 0 or quality > 5:
        raise ValueError(f"SM-2 quality must be between 0 and 5, got {quality}")

    mapping = {
        0: RATING_AGAIN,  # Complete blackout
        1: RATING_AGAIN,  # Incorrect but remembered upon seeing answer
        2: RATING_HARD,   # Incorrect but easy to recall
        3: RATING_HARD,   # Correct with serious difficulty
        4: RATING_GOOD,   # Correct after hesitation
        5: RATING_EASY,   # Perfect recall
    }
    return mapping[quality]


def migrate_sm2_to_fsrs(
    easiness_factor: float, repetitions: int, interval_days: int
) -> FSRSCard:
    """Migrate an existing SM-2 card state to an equivalent FSRS card state.

    Estimates FSRS stability and difficulty from SM-2 parameters:
    - Stability is derived from the current interval (which represents
      the expected time until recall drops to ~90% in SM-2).
    - Difficulty is estimated from the easiness factor (EF), where
      EF ranges from 1.3 (hardest) to 2.5+ (easiest).

    Args:
        easiness_factor: SM-2 easiness factor (typically 1.3 to 2.5+).
        repetitions: Number of successful repetitions in SM-2.
        interval_days: Current SM-2 interval in days.

    Returns:
        FSRSCard with estimated stability, difficulty, and appropriate state.

    Examples:
        >>> card = migrate_sm2_to_fsrs(2.5, 5, 30)
        >>> card.state  # Well-reviewed card -> Review state
        2
        >>> card.stability > 0
        True
    """
    # Estimate stability from SM-2 interval
    # In SM-2, the interval represents approximately when recall
    # would drop to ~90%, which aligns with FSRS's retention target.
    # FSRS stability at 90% retention: I = S * 9 * (1/0.9 - 1) ≈ S
    # So stability ≈ interval (they're roughly equivalent at 90% retention)
    if interval_days > 0:
        stability = float(interval_days)
    else:
        # New or reset card: use initial stability for Good rating
        stability = _initial_stability(RATING_GOOD)

    stability = _clamp_stability(stability)

    # Estimate difficulty from easiness factor
    # SM-2 EF ranges: 1.3 (hardest) to ~2.5+ (easiest)
    # FSRS D ranges: 1 (easiest) to 10 (hardest) — inverted relationship
    # Linear mapping: EF 1.3 -> D ~8.5, EF 2.5 -> D ~3.0
    # Formula: D = 10 - (EF - 1.3) * (7.0 / 1.2)
    ef_clamped = max(1.3, min(3.0, easiness_factor))
    difficulty = 10.0 - (ef_clamped - 1.3) * (7.0 / 1.2)
    difficulty = _clamp_difficulty(difficulty)

    # Determine card state based on repetition history
    if repetitions == 0:
        state = STATE_NEW
    elif repetitions <= 1:
        state = STATE_LEARNING
    else:
        state = STATE_REVIEW

    # Set last_review to today (migration moment)
    last_review = datetime.now().date().isoformat()

    return FSRSCard(
        stability=stability,
        difficulty=difficulty,
        state=state,
        last_review=last_review,
        reps=repetitions,
    )


# --- Utility / convenience functions ---


def get_intervals_for_all_ratings(
    card: FSRSCard, desired_retention: float = 0.9, review_date: str = None
) -> dict:
    """Preview the next interval for each possible rating.

    Useful for showing the user what each button would do.

    Args:
        card: Current card state.
        desired_retention: Target retention rate.
        review_date: Optional review date (ISO format).

    Returns:
        Dictionary mapping rating names to their resulting intervals.
        Example: {'again': 1, 'hard': 3, 'good': 7, 'easy': 21}
    """
    results = {}
    names = {1: 'again', 2: 'hard', 3: 'good', 4: 'easy'}

    for rating in range(1, 5):
        output = review_card(card, rating, desired_retention, review_date)
        results[names[rating]] = output.interval

    return results
