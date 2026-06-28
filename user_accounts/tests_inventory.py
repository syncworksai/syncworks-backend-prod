from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory,force_authenticate
from user_accounts.models import Business,BusinessMember,InventoryItem,InventoryLocation,InventoryStock,PurchaseOrder,PurchaseOrderLine,ServiceCategory,Ticket,TicketRequirement,Vendor
from user_accounts.viewsets.inventory import InventoryItemListCreateAPIView,PurchaseReceiptCreateAPIView,StockMovementCreateAPIView
class InventoryTests(TestCase):
    def setUp(self):
        U=get_user_model(); self.c=U.objects.create_user(username='ic',email='ic@test.com',password='x'); self.o=U.objects.create_user(username='io',email='io@test.com',password='x'); self.e=U.objects.create_user(username='ie',email='ie@test.com',password='x')
        self.b=Business.objects.create(owner=self.o,name='Inventory Co'); BusinessMember.objects.create(business=self.b,user=self.e,role='MANAGER',is_active=True)
        cat=ServiceCategory.objects.create(key='inv-service',name='Inv Service'); self.t=Ticket.objects.create(customer=self.c,assigned_business=self.b,assigned_member=self.e,category=cat,status='IN_PROGRESS')
        self.loc=InventoryLocation.objects.create(business=self.b,name='Main'); self.v=Vendor.objects.create(business=self.b,name='Vendor'); self.item=InventoryItem.objects.create(business=self.b,preferred_vendor=self.v,name='Compressor',sku='C-1',reorder_point=2); self.f=APIRequestFactory()
    def auth(self,r): force_authenticate(r,user=self.e); return r
    def test_reorder(self):
        r=self.f.get('/',HTTP_X_BUSINESS_ID=str(self.b.id)); x=InventoryItemListCreateAPIView.as_view()(self.auth(r)); self.assertEqual(x.status_code,200); self.assertTrue(x.data[0]['needs_reorder'])
    def test_receive(self):
        r=self.f.post('/',{'item':self.item.id,'location':self.loc.id,'movement_type':'RECEIVE','quantity':'4'},format='json',HTTP_X_BUSINESS_ID=str(self.b.id)); self.assertEqual(StockMovementCreateAPIView.as_view()(self.auth(r)).status_code,201); self.assertEqual(InventoryStock.objects.get(item=self.item).quantity_on_hand,Decimal('4'))
    def test_reserve_block(self):
        InventoryStock.objects.create(item=self.item,location=self.loc,quantity_on_hand=3)
        for qty,code in [('2',201),('2',400)]:
            r=self.f.post('/',{'item':self.item.id,'location':self.loc.id,'movement_type':'RESERVE','quantity':qty},format='json',HTTP_X_BUSINESS_ID=str(self.b.id)); self.assertEqual(StockMovementCreateAPIView.as_view()(self.auth(r)).status_code,code)
    def test_partial_receipt(self):
        po=PurchaseOrder.objects.create(business=self.b,vendor=self.v,po_number='PO1',status='SUBMITTED'); line=PurchaseOrderLine.objects.create(purchase_order=po,item=self.item,ticket=self.t,quantity_ordered=5)
        r=self.f.post('/',{'line':line.id,'location':self.loc.id,'quantity_received':'2'},format='json',HTTP_X_BUSINESS_ID=str(self.b.id)); self.assertEqual(PurchaseReceiptCreateAPIView.as_view()(self.auth(r),po_id=po.id).status_code,201); po.refresh_from_db(); self.assertEqual(po.status,'PARTIAL')
    def test_full_receipt_satisfies_part(self):
        req=TicketRequirement.objects.create(ticket=self.t,requirement_type='PART',title='Wait',metadata={'inventory_item_id':self.item.id}); po=PurchaseOrder.objects.create(business=self.b,vendor=self.v,po_number='PO2',status='SUBMITTED'); line=PurchaseOrderLine.objects.create(purchase_order=po,item=self.item,ticket=self.t,quantity_ordered=1)
        r=self.f.post('/',{'line':line.id,'location':self.loc.id,'quantity_received':'1'},format='json',HTTP_X_BUSINESS_ID=str(self.b.id)); self.assertEqual(PurchaseReceiptCreateAPIView.as_view()(self.auth(r),po_id=po.id).status_code,201); req.refresh_from_db(); self.assertEqual(req.status,'SATISFIED')
