"""Retry policy is independent of transport redelivery; unknown external effects stop."""

RETRYABLE = frozenset({"LOCAL_TRANSIENT", "LEASE_LOST", "TIMEOUT"})


def retry_delay(code, attempt_no, maximum):
    if not 1 <= attempt_no <= maximum:
        raise ValueError("Invalid attempt budget")
    if code not in RETRYABLE or attempt_no >= maximum:
        return None
    return min(300, 2 ** min(attempt_no, 9))
