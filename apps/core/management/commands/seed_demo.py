"""Populate the database with realistic demo data for local development."""
from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.core.models import AppSetting
from apps.customers.models import Customer
from apps.inventory.models import (
    Manufacturer,
    Product,
    ProductBatch,
    ProductCategory,
    StockMovement,
)
from apps.sales.services import checkout, add_to_cart
from apps.suppliers.models import PurchaseInvoice, Supplier

User = get_user_model()


CATEGORIES = [
    ("Antibiotics", "shield-plus"),
    ("Pain Relief", "capsule"),
    ("Vitamins", "heart-pulse"),
    ("Cold & Flu", "thermometer-half"),
    ("Diabetes", "droplet"),
    ("Skin Care", "sun"),
    ("Cardiac", "heart"),
    ("Digestive", "stars"),
]

MANUFACTURERS = ["Square Pharma", "Beximco", "Incepta", "ACI", "Renata", "Opsonin"]

PRODUCTS = [
    ("Napa", "Paracetamol", "500 mg", "Pain Relief", False),
    ("Napa Extra", "Paracetamol+Caffeine", "500 mg", "Pain Relief", False),
    ("Seclo", "Omeprazole", "20 mg", "Digestive", False),
    ("Maxpro", "Esomeprazole", "20 mg", "Digestive", False),
    ("Amoxin", "Amoxicillin", "500 mg", "Antibiotics", True),
    ("Cef-3", "Ceftriaxone", "1 g", "Antibiotics", True),
    ("Azimax", "Azithromycin", "500 mg", "Antibiotics", True),
    ("Glycomet", "Metformin", "500 mg", "Diabetes", False),
    ("Insulin R", "Insulin", "100 IU/ml", "Diabetes", False),
    ("Tusca Syrup", "Dextromethorphan", "60 ml", "Cold & Flu", False),
    ("Histacin", "Chlorpheniramine", "4 mg", "Cold & Flu", False),
    ("Vitamin C", "Ascorbic Acid", "500 mg", "Vitamins", False),
    ("Calcium D", "Calcium+VitD", "1000 mg", "Vitamins", False),
    ("Cardix", "Atenolol", "50 mg", "Cardiac", False),
    ("Lipitor", "Atorvastatin", "10 mg", "Cardiac", False),
]


class Command(BaseCommand):
    help = "Create demo users, categories, products, batches, customers, suppliers and sample invoices."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Wipe demo data before seeding")

    def handle(self, *args, **opts):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding demo data…"))

        if opts.get("reset"):
            self._reset()

        AppSetting.load()
        admin = self._ensure_admin()

        cats = {name: self._get_category(name, icon) for name, icon in CATEGORIES}
        mans = [Manufacturer.objects.get_or_create(name=name)[0] for name in MANUFACTURERS]
        products = self._seed_products(cats, mans)
        suppliers = self._seed_suppliers()
        customers = self._seed_customers()
        self._seed_purchase_invoices(suppliers)
        self._seed_sales(customers, products, admin)

        self.stdout.write(self.style.SUCCESS("Demo data ready. Login: admin / admin12345"))

    # ----- helpers --------------------------------------------------------
    def _reset(self):
        from apps.sales.models import (
            AntibioticRegisterEntry,
            InvoiceSequence,
            ReturnItem,
            ReturnTransaction,
            SalesInvoice,
            SalesInvoiceItem,
        )
        from apps.suppliers.models import PurchaseInvoice, Supplier, UploadedReceipt

        for model in (
            AntibioticRegisterEntry, ReturnItem, ReturnTransaction,
            SalesInvoiceItem, SalesInvoice, InvoiceSequence,
            UploadedReceipt, PurchaseInvoice, Supplier,
            StockMovement, ProductBatch, Product, Manufacturer, ProductCategory,
            Customer,
        ):
            model.objects.all().delete()
        self.stdout.write(self.style.WARNING("Existing demo data wiped."))

    def _ensure_admin(self):
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={"is_staff": True, "is_superuser": True, "email": "admin@example.com"},
        )
        if created or not admin.has_usable_password():
            admin.set_password("admin12345")
            admin.is_staff = True
            admin.is_superuser = True
            admin.save()
        return admin

    def _get_category(self, name, icon):
        cat, _ = ProductCategory.objects.get_or_create(name=name, defaults={"icon": icon})
        if not cat.icon:
            cat.icon = icon
            cat.save(update_fields=["icon"])
        return cat

    def _seed_products(self, cats, mans):
        products = []
        for name, generic, strength, cat_name, is_abx in PRODUCTS:
            prod, _ = Product.objects.get_or_create(
                name=name,
                defaults={
                    "generic_name": generic,
                    "strength": strength,
                    "category": cats[cat_name],
                    "manufacturer": random.choice(mans),
                    "is_antibiotic": is_abx,
                    "requires_prescription": is_abx,
                    "description": f"{name} ({generic}) {strength} for demo purposes.",
                },
            )
            if not prod.batches.exists():
                self._seed_batches(prod)
            products.append(prod)
        return products

    def _seed_batches(self, product: Product):
        today = timezone.localdate()
        for i in range(random.randint(1, 2)):
            batch = ProductBatch.objects.create(
                product=product,
                batch_number=f"B-{product.id:03d}-{i+1}",
                expiry_date=today + timedelta(days=random.randint(45, 540)),
                buy_price=Decimal(random.choice([4, 5, 6, 8, 10, 12, 15])),
                tp_price=Decimal(random.choice([8, 10, 12, 15, 18, 20, 25])),
                mrp=Decimal(random.choice([10, 12, 15, 18, 22, 25, 30])),
                quantity=random.randint(40, 200),
                shelf_location=random.choice(["A1", "A2", "B1", "B2", "C1"]),
            )
            StockMovement.objects.create(
                batch=batch,
                movement_type=StockMovement.TYPE_INITIAL,
                quantity=batch.quantity,
                note="Seed data",
            )

    def _seed_suppliers(self):
        names = [
            ("Square Distribution", "Mr. Karim", "01711000001"),
            ("Beximco Depot", "Mr. Rahim", "01711000002"),
            ("Incepta Supplies", "Ms. Sara", "01711000003"),
        ]
        out = []
        for name, contact, phone in names:
            s, _ = Supplier.objects.get_or_create(
                name=name,
                defaults={"contact_person": contact, "phone": phone, "address": "Dhaka, BD"},
            )
            out.append(s)
        return out

    def _seed_customers(self):
        names = [
            ("Rahim Uddin", "01911000001"),
            ("Karim Mia", "01911000002"),
            ("Salma Akter", "01911000003"),
            ("Jamal Hossain", "01911000004"),
            ("Mizan Rahman", "01911000005"),
            ("Nadia Sultana", "01911000006"),
            ("Walk-in", "00000000000"),
        ]
        out = []
        for name, phone in names:
            c, _ = Customer.objects.get_or_create(phone=phone, defaults={"name": name})
            out.append(c)
        return out

    def _seed_purchase_invoices(self, suppliers):
        today = timezone.localdate()
        for s in suppliers:
            if s.purchase_invoices.exists():
                continue
            for n in range(2):
                total = Decimal(random.randint(2000, 15000))
                paid = total if random.random() < 0.5 else total - Decimal(random.randint(500, 1500))
                PurchaseInvoice.objects.create(
                    supplier=s,
                    invoice_number=f"PI-{s.id}-{n+1}",
                    invoice_date=today - timedelta(days=random.randint(2, 60)),
                    subtotal=total,
                    total=total,
                    paid_amount=paid,
                    due_amount=total - paid,
                )

    def _seed_sales(self, customers, products, admin):
        from apps.sales.models import SalesInvoice
        if SalesInvoice.objects.count() >= 6:
            return
        from importlib import import_module
        from django.conf import settings

        engine = import_module(settings.SESSION_ENGINE)

        for i in range(6):
            customer = random.choice(customers)
            session = engine.SessionStore()
            session.create()
            pick = random.sample(products, k=random.randint(2, 4))
            for p in pick:
                batch = p.sellable_batches().first()
                if not batch:
                    continue
                add_to_cart(
                    session,
                    product_id=p.id,
                    batch_id=batch.id,
                    quantity=random.randint(1, 4),
                    unit_price=batch.tp_price,
                )
            if not session.get("cart"):
                continue
            paid_full = random.random() < 0.6
            try:
                inv = checkout(
                    session=session,
                    customer=customer,
                    discount_type="fixed",
                    discount_value=Decimal(random.choice([0, 0, 10, 20])),
                    paid_amount=Decimal("99999") if paid_full else Decimal(random.randint(50, 300)),
                    user=admin,
                )
                # If paid was overshot, adjust to total.
                if inv.paid_amount > inv.total:
                    inv.paid_amount = inv.total
                    inv.recalc_status()
                    inv.save()
            except Exception as exc:
                self.stderr.write(f"Could not seed an invoice: {exc}")
