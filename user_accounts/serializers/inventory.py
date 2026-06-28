from rest_framework import serializers
from user_accounts.models import InventoryItem,InventoryLocation,InventoryStock,PurchaseOrder,PurchaseOrderLine,PurchaseReceipt,StockMovement,Vendor
class InventoryLocationSerializer(serializers.ModelSerializer):
    class Meta: model=InventoryLocation; fields='__all__'; read_only_fields=['id','business','created_at']
class VendorSerializer(serializers.ModelSerializer):
    class Meta: model=Vendor; fields='__all__'; read_only_fields=['id','business','created_at']
class InventoryItemSerializer(serializers.ModelSerializer):
    total_on_hand=serializers.DecimalField(max_digits=14,decimal_places=3,read_only=True); total_reserved=serializers.DecimalField(max_digits=14,decimal_places=3,read_only=True)
    total_available=serializers.SerializerMethodField(); needs_reorder=serializers.SerializerMethodField()
    class Meta:
        model=InventoryItem; fields=['id','business','preferred_vendor','name','sku','barcode','unit','reorder_point','reorder_quantity','unit_cost','metadata','is_active','total_on_hand','total_reserved','total_available','needs_reorder','created_at','updated_at']; read_only_fields=['id','business','total_on_hand','total_reserved','total_available','needs_reorder','created_at','updated_at']
    def get_total_available(self,o): return (getattr(o,'total_on_hand',0) or 0)-(getattr(o,'total_reserved',0) or 0)
    def get_needs_reorder(self,o): return self.get_total_available(o)<=o.reorder_point
class InventoryStockSerializer(serializers.ModelSerializer):
    quantity_available=serializers.DecimalField(max_digits=14,decimal_places=3,read_only=True)
    class Meta: model=InventoryStock; fields='__all__'
class StockMovementSerializer(serializers.ModelSerializer):
    class Meta: model=StockMovement; fields='__all__'; read_only_fields=['id','quantity_after','created_by','created_at']
class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    class Meta: model=PurchaseOrderLine; fields='__all__'; read_only_fields=['id','purchase_order','quantity_received']
class PurchaseOrderSerializer(serializers.ModelSerializer):
    lines=PurchaseOrderLineSerializer(many=True,read_only=True)
    class Meta: model=PurchaseOrder; fields=['id','business','vendor','po_number','status','expected_at','notes','lines','created_at','updated_at']; read_only_fields=['id','business','lines','created_at','updated_at']
class PurchaseReceiptSerializer(serializers.ModelSerializer):
    class Meta: model=PurchaseReceipt; fields='__all__'; read_only_fields=['id','purchase_order','received_by','received_at']
