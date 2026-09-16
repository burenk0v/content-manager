"""Errors shared by asynchronous application jobs."""


class JobError(Exception):
    """Base error for application job failures."""


class UnknownJobTypeError(JobError):
    """Raised when no handler is registered for a durable job type."""


class RetryableJobError(JobError):
    """Raised when a handler knows that a job should be retried."""


class PermanentJobError(JobError):
    """Raised when retrying cannot make a job succeed."""
