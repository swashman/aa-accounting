"""Views."""

# Django
from django.contrib.auth.decorators import login_required, permission_required
from django.core.handlers.wsgi import WSGIRequest
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import render

# Accounting
from accounting.models import CorpAccount, UnclaimedTax, UserAccount


@login_required
@permission_required("accounting.view_all")
def dashboard(request: WSGIRequest) -> HttpResponse:

    # sum outstanding user accounts
    user_total = (
        UserAccount.objects.outstanding().aggregate(total=Sum("balance"))["total"] or 0
    )
    corp_total = (
        CorpAccount.objects.outstanding().aggregate(total=Sum("balance"))["total"] or 0
    )
    total_outstanding = user_total + corp_total

    unclaimed_total = UnclaimedTax.objects.aggregate(total=Sum("amount"))["total"] or 0
    context = {
        "total_outstanding": total_outstanding,
        "unclaimed_total": unclaimed_total,
    }

    return render(request, "accounting/admin-dashboard.html", context)


@login_required
@permission_required("accounting.view_all")
def corporations(request: WSGIRequest) -> HttpResponse:

    context = {"character_id": 2113982619}

    return render(request, "accounting/admin-corporations.html", context)


@login_required
@permission_required("accounting.view_all")
def characters(request: WSGIRequest) -> HttpResponse:

    context = {"character_id": 2113982619}

    return render(request, "accounting/admin-characters.html", context)


@login_required
@permission_required("accounting.finance_manager")
def manual(request: WSGIRequest) -> HttpResponse:

    context = {"character_id": 2113982619}

    return render(request, "accounting/admin-manual.html", context)
