"""First-stage retrieval router package."""

__all__ = ["retrieve_contexts"]


def retrieve_contexts(*args, **kwargs):
    from .pipeline import retrieve_contexts as _retrieve_contexts

    return _retrieve_contexts(*args, **kwargs)
