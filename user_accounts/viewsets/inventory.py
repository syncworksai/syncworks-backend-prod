from decimal import Decimal
from django.db import IntegrityError,transaction
from django.db.models import DecimalField,Sum,Value
from django.db.models.functions import Coalesce
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from user_accounts.models import InventoryItem,InventoryLocation,InventoryStock,PurchaseOrder,PurchaseOrderLine,PurchaseReceipt,StockMovement,TicketRequirement,Vendor
from user_accounts.serializers.inventory import InventoryItemSerializer,InventoryLocationSerializer,InventoryStockSerializer,PurchaseOrderLineSerializer,PurchaseOrderSerializer,PurchaseReceiptSerializer,StockMovementSerializer,VendorSerializer
from user_accounts.viewsets.ticket_conversations import _business_context,_visible_tickets
ZERO=Value(Decimal('0'),output_field=DecimalField(max_digits=14,decimal_places=3))
def items_qs(b): return InventoryItem.objects.filter(business=b).annotate(total_on_hand=Coalesce(Sum('stock_records__quantity_on_hand'),ZERO),total_reserved=Coalesce(Sum('stock_records__quantity_reserved'),ZERO))
class InventoryLocationListCreateAPIView(APIView):
    permission_classes=[IsAuthenticated]
    def get(self,r):
        b,_,_=_business_context(r); return Response(InventoryLocationSerializer(InventoryLocation.objects.filter(business=b),many=True).data)
    def post(self,r):
        b,_,_=_business_context(r); s=InventoryLocationSerializer(data=r.data); s.is_valid(raise_exception=True)
        try: row=s.save(business=b)
        except IntegrityError: raise ValidationError({'name':'Location already exists.'})
        return Response(InventoryLocationSerializer(row).data,status=201)
class VendorListCreateAPIView(APIView):
    permission_classes=[IsAuthenticated]
    def get(self,r):
        b,_,_=_business_context(r); return Response(VendorSerializer(Vendor.objects.filter(business=b),many=True).data)
    def post(self,r):
        b,_,_=_business_context(r); s=VendorSerializer(data=r.data); s.is_valid(raise_exception=True)
        try: row=s.save(business=b)
        except IntegrityError: raise ValidationError({'name':'Vendor already exists.'})
        return Response(VendorSerializer(row).data,status=201)
class InventoryItemListCreateAPIView(APIView):
    permission_classes=[IsAuthenticated]
    def get(self,r):
        b,_,_=_business_context(r); rows=list(items_qs(b)[:500])
        if str(r.query_params.get('reorder_only') or '').lower() in {'1','true','yes'}: rows=[x for x in rows if x.total_on_hand-x.total_reserved<=x.reorder_point]
        return Response(InventoryItemSerializer(rows,many=True).data)
    def post(self,r):
        b,_,_=_business_context(r); s=InventoryItemSerializer(data=r.data); s.is_valid(raise_exception=True)
        v=s.validated_data.get('preferred_vendor')
        if v and v.business_id!=b.id: raise ValidationError({'preferred_vendor':'Wrong business.'})
        try: row=s.save(business=b)
        except IntegrityError: raise ValidationError({'sku':'SKU already exists.'})
        row.total_on_hand=Decimal('0'); row.total_reserved=Decimal('0')
        return Response(InventoryItemSerializer(row).data,status=201)
class InventoryStockListAPIView(APIView):
    permission_classes=[IsAuthenticated]
    def get(self,r):
        b,_,_=_business_context(r); q=InventoryStock.objects.filter(item__business=b).select_related('item','location'); return Response(InventoryStockSerializer(q,many=True).data)
class StockMovementCreateAPIView(APIView):
    permission_classes=[IsAuthenticated]
    def post(self,r):
        b,_,_=_business_context(r); item=InventoryItem.objects.filter(id=r.data.get('item'),business=b).first(); loc=InventoryLocation.objects.filter(id=r.data.get('location'),business=b).first()
        if not item or not loc: raise ValidationError('Item or location not found.')
        ticket=None
        if r.data.get('ticket'):
            ticket=_visible_tickets(r,'BUSINESS').filter(id=r.data.get('ticket')).first()
            if not ticket: raise ValidationError({'ticket':'Ticket not found.'})
        typ=str(r.data.get('movement_type') or '').upper(); qty=Decimal(str(r.data.get('quantity') or '0'))
        if qty<=0: raise ValidationError({'quantity':'Must be greater than zero.'})
        with transaction.atomic():
            stock,_=InventoryStock.objects.select_for_update().get_or_create(item=item,location=loc)
            if typ=='RECEIVE': stock.quantity_on_hand+=qty
            elif typ=='ISSUE':
                if stock.quantity_available<qty: raise ValidationError({'quantity':'Insufficient inventory.'})
                stock.quantity_on_hand-=qty
            elif typ=='RESERVE':
                if stock.quantity_available<qty: raise ValidationError({'quantity':'Insufficient inventory.'})
                stock.quantity_reserved+=qty
            elif typ=='RELEASE':
                if stock.quantity_reserved<qty: raise ValidationError({'quantity':'Cannot release more than reserved.'})
                stock.quantity_reserved-=qty
            elif typ=='ADJUST':
                new=Decimal(str(r.data.get('quantity_after') or '-1'))
                if new<0: raise ValidationError({'quantity_after':'Cannot be negative.'})
                stock.quantity_on_hand=new
            else: raise ValidationError({'movement_type':'Invalid movement type.'})
            stock.save(); m=StockMovement.objects.create(item=item,location=loc,ticket=ticket,movement_type=typ,quantity=qty,quantity_after=stock.quantity_on_hand,note=str(r.data.get('note') or ''),created_by=r.user)
        return Response(StockMovementSerializer(m).data,status=201)
class PurchaseOrderListCreateAPIView(APIView):
    permission_classes=[IsAuthenticated]
    def get(self,r):
        b,_,_=_business_context(r); q=PurchaseOrder.objects.filter(business=b).prefetch_related('lines'); return Response(PurchaseOrderSerializer(q,many=True).data)
    def post(self,r):
        b,_,_=_business_context(r); s=PurchaseOrderSerializer(data=r.data); s.is_valid(raise_exception=True)
        if s.validated_data['vendor'].business_id!=b.id: raise ValidationError({'vendor':'Wrong business.'})
        try: po=s.save(business=b,created_by=r.user)
        except IntegrityError: raise ValidationError({'po_number':'PO number already exists.'})
        return Response(PurchaseOrderSerializer(po).data,status=201)
class PurchaseOrderLineCreateAPIView(APIView):
    permission_classes=[IsAuthenticated]
    def post(self,r,po_id):
        b,_,_=_business_context(r); po=PurchaseOrder.objects.filter(id=po_id,business=b).first()
        if not po: raise Http404
        s=PurchaseOrderLineSerializer(data=r.data); s.is_valid(raise_exception=True)
        if s.validated_data['item'].business_id!=b.id: raise ValidationError({'item':'Wrong business.'})
        line=s.save(purchase_order=po); return Response(PurchaseOrderLineSerializer(line).data,status=201)
class PurchaseReceiptCreateAPIView(APIView):
    permission_classes=[IsAuthenticated]
    def post(self,r,po_id):
        b,_,_=_business_context(r); po=PurchaseOrder.objects.filter(id=po_id,business=b).first()
        if not po: raise Http404
        line=PurchaseOrderLine.objects.select_related('item','ticket').filter(id=r.data.get('line'),purchase_order=po).first(); loc=InventoryLocation.objects.filter(id=r.data.get('location'),business=b).first()
        if not line or not loc: raise ValidationError('Line or location not found.')
        qty=Decimal(str(r.data.get('quantity_received') or '0'))
        if qty<=0 or qty>line.quantity_ordered-line.quantity_received: raise ValidationError({'quantity_received':'Invalid receipt quantity.'})
        with transaction.atomic():
            line=PurchaseOrderLine.objects.select_for_update().get(id=line.id)
            if qty>line.quantity_ordered-line.quantity_received: raise ValidationError({'quantity_received':'Exceeds remaining quantity.'})
            line.quantity_received+=qty; line.save(update_fields=['quantity_received'])
            stock,_=InventoryStock.objects.select_for_update().get_or_create(item=line.item,location=loc); stock.quantity_on_hand+=qty; stock.save()
            receipt=PurchaseReceipt.objects.create(purchase_order=po,line=line,location=loc,quantity_received=qty,received_by=r.user,note=str(r.data.get('note') or ''))
            StockMovement.objects.create(item=line.item,location=loc,ticket=line.ticket,movement_type='RECEIVE',quantity=qty,quantity_after=stock.quantity_on_hand,note=f'Received against {po.po_number}',created_by=r.user)
            po.status='RECEIVED' if all(x.quantity_received>=x.quantity_ordered for x in po.lines.all()) else 'PARTIAL'; po.save(update_fields=['status','updated_at'])
            if line.ticket_id and line.quantity_received>=line.quantity_ordered:
                TicketRequirement.objects.filter(ticket_id=line.ticket_id,requirement_type='PART',status='OPEN',metadata__inventory_item_id=line.item_id).update(status='SATISFIED',satisfied_at=timezone.now(),satisfied_by=r.user)
        return Response(PurchaseReceiptSerializer(receipt).data,status=201)
