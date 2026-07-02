from __future__ import annotations
import re
from django.db import transaction
from django.db.models import Q
from rest_framework import status,viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from user_accounts.models import BusinessCustomer
from user_accounts.serializers.business_customers import BusinessCustomerSerializer
from user_accounts.viewsets.ticket_conversations import _business_context

def _phone(value): return re.sub(r"\D+","",str(value or ""))[-15:]
class BusinessCustomerViewSet(viewsets.ModelViewSet):
    serializer_class=BusinessCustomerSerializer; permission_classes=[IsAuthenticated]
    def _context(self): return _business_context(self.request)
    def get_queryset(self):
        business,_,_=self._context(); qs=BusinessCustomer.objects.filter(business=business).select_related("business","last_ticket","created_by","updated_by")
        search=str(self.request.query_params.get("search") or "").strip()
        if search:
            digits=_phone(search); query=Q(name__icontains=search)|Q(company_name__icontains=search)|Q(email__icontains=search)|Q(phone__icontains=search)|Q(service_address__icontains=search)|Q(city__icontains=search)|Q(service_zip__icontains=search)|Q(external_customer_id__icontains=search)
            if digits: query|=Q(normalized_phone__contains=digits)
            qs=qs.filter(query)
        imported=str(self.request.query_params.get("imported") or "").lower()
        if imported in {"1","true","yes"}: qs=qs.filter(is_imported=True)
        elif imported in {"0","false","no"}: qs=qs.filter(is_imported=False)
        source=str(self.request.query_params.get("source_system") or "").strip()
        if source: qs=qs.filter(source_system__iexact=source)
        return qs.order_by("-updated_at","-id")
    def perform_create(self,serializer):
        business,_,_=self._context(); serializer.save(business=business,created_by=self.request.user,updated_by=self.request.user)
    def perform_update(self,serializer):
        business,_,_=self._context()
        if serializer.instance.business_id!=business.id: raise ValidationError({"business":"Customer belongs to another business."})
        serializer.save(updated_by=self.request.user)
    @action(detail=False,methods=["post"],url_path="resolve")
    def resolve(self,request):
        business,_,_=self._context(); payload=request.data.copy(); source=str(payload.get("source_system") or "").strip(); ext=str(payload.get("external_customer_id") or "").strip(); email=str(payload.get("email") or "").strip().lower(); phone=_phone(payload.get("phone")); name=str(payload.get("name") or "").strip(); address=str(payload.get("service_address") or "").strip(); customer=None; matched=""
        if source and ext: customer=BusinessCustomer.objects.filter(business=business,source_system__iexact=source,external_customer_id=ext).first(); matched="external_customer_id" if customer else ""
        if not customer and email: customer=BusinessCustomer.objects.filter(business=business,email__iexact=email).first(); matched="email" if customer else ""
        if not customer and phone: customer=BusinessCustomer.objects.filter(business=business,normalized_phone=phone).first(); matched="phone" if customer else ""
        if not customer and name and address: customer=BusinessCustomer.objects.filter(business=business,name__iexact=name,service_address__iexact=address).first(); matched="name_and_address" if customer else ""
        s=self.get_serializer(customer,data=payload,partial=bool(customer)); s.is_valid(raise_exception=True)
        with transaction.atomic():
            if customer: row=s.save(updated_by=request.user); created=False
            else: row=s.save(business=business,created_by=request.user,updated_by=request.user); created=True
        return Response({"created":created,"matched_by":matched or "new","customer":self.get_serializer(row).data},status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
