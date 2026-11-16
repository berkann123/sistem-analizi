from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import InventoryItem, InventoryMovement
from .stock import replay_movements


def refresh_item_totals(item_id, using=None):
    """Ürünün stok ve hareketli ortalama maliyetini hareket geçmişinden yeniden hesaplar."""
    item = InventoryItem.objects.using(using).filter(pk=item_id).first()
    if item is None:
        return
    movements = (
        InventoryMovement.objects.using(using).filter(item_id=item_id)
        .order_by("movement_at", "created_at", "pk")
        .values_list("movement_type", "quantity", "unit_cost")
    )
    stock, average_cost = replay_movements(movements, fallback_cost=item.average_unit_cost)
    InventoryItem.objects.using(using).filter(pk=item_id).update(
        current_stock=stock, average_unit_cost=average_cost,
    )


@receiver(pre_save, sender=InventoryMovement)
def remember_previous_item(sender, instance, using, **kwargs):
    # Hareket başka bir ürüne taşınırsa eski ürünün toplamı da güncellenmeli.
    previous = sender.objects.using(using).filter(pk=instance.pk).values_list("item_id", flat=True).first()
    instance._previous_item_id = previous


@receiver(post_save, sender=InventoryMovement)
def refresh_stock_after_movement_save(sender, instance, using, **kwargs):
    refresh_item_totals(instance.item_id, using)
    previous = getattr(instance, "_previous_item_id", None)
    if previous and previous != instance.item_id:
        refresh_item_totals(previous, using)


@receiver(post_delete, sender=InventoryMovement)
def refresh_stock_after_movement_delete(sender, instance, using, **kwargs):
    refresh_item_totals(instance.item_id, using)
