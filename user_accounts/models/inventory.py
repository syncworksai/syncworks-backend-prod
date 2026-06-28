from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone
from .business import Business
from .tickets import Ticket

class InventoryLocation(models.Model):
    business=models.ForeignKey(Business,on_delete=models.CASCADE,related_name='inventory_locations')
    name=models.CharField(max_length=160)
    code=models.CharField(max_length=64,blank=True,default='')
    is_active=models.BooleanField(default=True)
    created_at=models.DateTimeField(default=timezone.now)
    class Meta:
        ordering=['name','id']
        constraints=[models.UniqueConstraint(fields=['business','name'],name='ua_inv_location_unique')]

class Vendor(models.Model):
    business=models.ForeignKey(Business,on_delete=models.CASCADE,related_name='vendors')
    name=models.CharField(max_length=180)
    contact_name=models.CharField(max_length=160,blank=True,default='')
    email=models.EmailField(blank=True,default='')
    phone=models.CharField(max_length=40,blank=True,default='')
    notes=models.TextField(blank=True,default='')
    is_active=models.BooleanField(default=True)
    created_at=models.DateTimeField(default=timezone.now)
    class Meta:
        ordering=['name','id']
        constraints=[models.UniqueConstraint(fields=['business','name'],name='ua_vendor_name_unique')]

class InventoryItem(models.Model):
    business=models.ForeignKey(Business,on_delete=models.CASCADE,related_name='inventory_items')
    preferred_vendor=models.ForeignKey(Vendor,on_delete=models.SET_NULL,null=True,blank=True,related_name='preferred_items')
    name=models.CharField(max_length=180)
    sku=models.CharField(max_length=100,blank=True,default='')
    barcode=models.CharField(max_length=160,blank=True,default='')
    unit=models.CharField(max_length=32,default='each')
    reorder_point=models.DecimalField(max_digits=12,decimal_places=3,default=Decimal('0'))
    reorder_quantity=models.DecimalField(max_digits=12,decimal_places=3,default=Decimal('0'))
    unit_cost=models.DecimalField(max_digits=12,decimal_places=2,default=Decimal('0'))
    metadata=models.JSONField(default=dict,blank=True)
    is_active=models.BooleanField(default=True)
    created_at=models.DateTimeField(default=timezone.now)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        ordering=['name','id']
        constraints=[models.UniqueConstraint(fields=['business','sku'],condition=~models.Q(sku=''),name='ua_inv_item_sku_unique')]
        indexes=[models.Index(fields=['business','is_active'],name='ua_inv_item_active_idx'),models.Index(fields=['business','barcode'],name='ua_inv_item_barcode_idx')]

class InventoryStock(models.Model):
    item=models.ForeignKey(InventoryItem,on_delete=models.CASCADE,related_name='stock_records')
    location=models.ForeignKey(InventoryLocation,on_delete=models.CASCADE,related_name='stock_records')
    quantity_on_hand=models.DecimalField(max_digits=14,decimal_places=3,default=Decimal('0'))
    quantity_reserved=models.DecimalField(max_digits=14,decimal_places=3,default=Decimal('0'))
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['item','location'],name='ua_inv_stock_unique'),models.CheckConstraint(condition=models.Q(quantity_on_hand__gte=0),name='ua_inv_stock_nonnegative'),models.CheckConstraint(condition=models.Q(quantity_reserved__gte=0),name='ua_inv_reserved_nonnegative')]
    @property
    def quantity_available(self): return self.quantity_on_hand-self.quantity_reserved

class StockMovement(models.Model):
    class MovementType(models.TextChoices):
        RECEIVE='RECEIVE','Receive'; ISSUE='ISSUE','Issue'; ADJUST='ADJUST','Adjust'; RESERVE='RESERVE','Reserve'; RELEASE='RELEASE','Release'
    item=models.ForeignKey(InventoryItem,on_delete=models.CASCADE,related_name='movements')
    location=models.ForeignKey(InventoryLocation,on_delete=models.CASCADE,related_name='movements')
    ticket=models.ForeignKey(Ticket,on_delete=models.SET_NULL,null=True,blank=True,related_name='stock_movements')
    movement_type=models.CharField(max_length=20,choices=MovementType.choices)
    quantity=models.DecimalField(max_digits=14,decimal_places=3)
    quantity_after=models.DecimalField(max_digits=14,decimal_places=3)
    note=models.CharField(max_length=255,blank=True,default='')
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='stock_movements_created')
    created_at=models.DateTimeField(default=timezone.now)
    class Meta:
        ordering=['-created_at','-id']
        indexes=[models.Index(fields=['item','created_at'],name='ua_stock_item_time_idx'),models.Index(fields=['ticket','created_at'],name='ua_stock_ticket_time_idx')]

class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT='DRAFT','Draft'; SUBMITTED='SUBMITTED','Submitted'; PARTIAL='PARTIAL','Partial'; RECEIVED='RECEIVED','Received'; CANCELLED='CANCELLED','Cancelled'
    business=models.ForeignKey(Business,on_delete=models.CASCADE,related_name='purchase_orders')
    vendor=models.ForeignKey(Vendor,on_delete=models.PROTECT,related_name='purchase_orders')
    po_number=models.CharField(max_length=80)
    status=models.CharField(max_length=20,choices=Status.choices,default=Status.DRAFT)
    expected_at=models.DateTimeField(null=True,blank=True)
    notes=models.TextField(blank=True,default='')
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='purchase_orders_created')
    created_at=models.DateTimeField(default=timezone.now)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        ordering=['-created_at','-id']
        constraints=[models.UniqueConstraint(fields=['business','po_number'],name='ua_po_number_unique')]

class PurchaseOrderLine(models.Model):
    purchase_order=models.ForeignKey(PurchaseOrder,on_delete=models.CASCADE,related_name='lines')
    item=models.ForeignKey(InventoryItem,on_delete=models.PROTECT,related_name='purchase_order_lines')
    ticket=models.ForeignKey(Ticket,on_delete=models.SET_NULL,null=True,blank=True,related_name='purchase_order_lines')
    quantity_ordered=models.DecimalField(max_digits=14,decimal_places=3)
    quantity_received=models.DecimalField(max_digits=14,decimal_places=3,default=Decimal('0'))
    unit_cost=models.DecimalField(max_digits=12,decimal_places=2,default=Decimal('0'))
    note=models.CharField(max_length=255,blank=True,default='')
    class Meta:
        ordering=['id']
        constraints=[models.CheckConstraint(condition=models.Q(quantity_ordered__gt=0),name='ua_po_ordered_positive'),models.CheckConstraint(condition=models.Q(quantity_received__gte=0),name='ua_po_received_nonnegative')]

class PurchaseReceipt(models.Model):
    purchase_order=models.ForeignKey(PurchaseOrder,on_delete=models.CASCADE,related_name='receipts')
    line=models.ForeignKey(PurchaseOrderLine,on_delete=models.CASCADE,related_name='receipts')
    location=models.ForeignKey(InventoryLocation,on_delete=models.PROTECT,related_name='purchase_receipts')
    quantity_received=models.DecimalField(max_digits=14,decimal_places=3)
    received_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='purchase_receipts_created')
    received_at=models.DateTimeField(default=timezone.now)
    note=models.CharField(max_length=255,blank=True,default='')
    class Meta:
        ordering=['-received_at','-id']
        constraints=[models.CheckConstraint(condition=models.Q(quantity_received__gt=0),name='ua_receipt_positive')]
