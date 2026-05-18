from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from pharmacy.models import AppSetting, Customer, Product, ProductBatch, ProductBrand, ProductCategory, Supplier
from pharmacy.services import add_or_update_cart_item, finalize_checkout


class SessionLike(dict):
    modified = False


class Command(BaseCommand):
    help = "Seed the pharmacy ERP with realistic starter data."

    def handle(self, *args, **options):
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username="admin",
            defaults={"email": "admin@example.com", "is_staff": True, "is_superuser": True},
        )
        if created:
            user.set_password("admin12345")
            user.save()

        AppSetting.objects.update_or_create(
            pk=1,
            defaults={
                "store_name": "Ashafa Traders Pharmacy",
                "store_phone": "+8801700000000",
                "store_email": "hello@ashafa.example",
                "store_address": "Main Road, Pharmacy Market",
                "invoice_footer": "Thank you for choosing Ashafa Traders Pharmacy.",
            },
        )

        categories = {}
        for name, color in [
            ("Antibiotics", "#2563eb"),
            ("Pain relief", "#0ea5e9"),
            ("Diabetes care", "#16a34a"),
            ("Cardiac care", "#9333ea"),
            ("Vitamins", "#f97316"),
        ]:
            categories[name], _ = ProductCategory.objects.get_or_create(name=name, defaults={"color": color})

        brands = {}
        for name in ["Acme Pharma", "Square Health", "Beximco Care", "Renata Labs"]:
            brands[name], _ = ProductBrand.objects.get_or_create(name=name)

        products = [
            ("Amoxicillin", "Amoxicillin", "500mg", "Capsule", "Antibiotics", "Acme Pharma", True, Decimal("14.00"), Decimal("18.00"), Decimal("22.00")),
            ("Azithro", "Azithromycin", "500mg", "Tablet", "Antibiotics", "Square Health", True, Decimal("28.00"), Decimal("35.00"), Decimal("40.00")),
            ("Napa", "Paracetamol", "500mg", "Tablet", "Pain relief", "Beximco Care", False, Decimal("1.20"), Decimal("1.80"), Decimal("2.00")),
            ("Metformin", "Metformin", "850mg", "Tablet", "Diabetes care", "Renata Labs", False, Decimal("3.50"), Decimal("5.00"), Decimal("6.00")),
            ("Amlodipine", "Amlodipine", "5mg", "Tablet", "Cardiac care", "Square Health", False, Decimal("4.00"), Decimal("6.00"), Decimal("7.00")),
            ("Vitamin D3", "Cholecalciferol", "2000 IU", "Tablet", "Vitamins", "Acme Pharma", False, Decimal("6.00"), Decimal("8.00"), Decimal("10.00")),
        ]
        for index, (name, generic, strength, dosage, category, brand, antibiotic, buy, tp, mrp) in enumerate(products, start=1):
            product, _ = Product.objects.update_or_create(
                name=name,
                strength=strength,
                defaults={
                    "generic_name": generic,
                    "dosage_form": dosage,
                    "category": categories[category],
                    "brand": brands[brand],
                    "is_antibiotic": antibiotic,
                    "barcode": f"88010000000{index}",
                    "sku": f"MED-{index:04d}",
                    "reorder_level": 20,
                },
            )
            ProductBatch.objects.update_or_create(
                product=product,
                batch_number=f"BATCH-{index:03d}",
                defaults={
                    "expiry_date": timezone.localdate() + timedelta(days=180 + index * 20),
                    "buy_price": buy,
                    "tp_price": tp,
                    "mrp": mrp,
                    "stock_quantity": 80 - index * 6,
                    "shelf_number": f"S-{index}",
                },
            )

        Customer.objects.get_or_create(name="Rahim Uddin", phone="01710000001")
        Customer.objects.get_or_create(name="Nusrat Jahan", phone="01710000002")
        Supplier.objects.get_or_create(name="Central Medicine Supply", phone="01910000001", defaults={"opening_due": Decimal("1200.00")})

        if not ProductBatch.objects.filter(sales_items__isnull=False).exists():
            session = SessionLike()
            first_batch = ProductBatch.objects.select_related("product").first()
            if first_batch:
                add_or_update_cart_item(session, first_batch.id, quantity=2)
                finalize_checkout(
                    session,
                    {
                        "customer_name": "Rahim Uddin",
                        "customer_phone": "01710000001",
                        "discount_percent": Decimal("0.00"),
                        "discount_amount": Decimal("0.00"),
                        "paid_amount": first_batch.tp_price,
                        "notes": "Seed invoice",
                    },
                    user,
                )

        self.stdout.write(self.style.SUCCESS("Seed data ready. Login with admin / admin12345."))
