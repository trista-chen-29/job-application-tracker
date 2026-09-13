from __future__ import annotations

from django.shortcuts import get_object_or_404


def owned(model, user, pk: int):
    return get_object_or_404(model, pk=pk, user=user)
