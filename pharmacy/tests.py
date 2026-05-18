from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Product, ProductBatch, ProductCategory, SalesInvoice, StockMovement
from .services import add_or_update_cart_item, finalize_checkout


class SessionLike(dict):
    modified = False


class PharmacyWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("staff", password="pass", is_staff=True)
        category = ProductCategory.objects.create(name="Antibiotics")
        self.product = Product.objects.create(
            name="Amoxicillin",
            generic_name="Amoxicillin",
            strength="500mg",
            category=category,
            is_antibiotic=True,
            reorder_level=5,
        )
        self.batch = ProductBatch.objects.create(
            product=self.product,
            batch_number="A-001",
            expiry_date=timezone.localdate() + timedelta(days=180),
            buy_price=Decimal("10.00"),
            tp_price=Decimal("14.00"),
            mrp=Decimal("18.00"),
            stock_quantity=10,
        )

    def test_checkout_creates_invoice_and_decrements_stock(self):
        session = SessionLike()
        session["pending_invoice_number"] = "INV-20990101-0001"
        add_or_update_cart_item(session, self.batch.id, quantity=2)

        invoice = finalize_checkout(
            session,
            {
                "customer_name": "Test Customer",
                "customer_phone": "01710000000",
                "discount_percent": Decimal("0.00"),
                "discount_amount": Decimal("0.00"),
                "paid_amount": Decimal("20.00"),
                "notes": "",
            },
            self.user,
        )

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.stock_quantity, 8)
        self.assertEqual(invoice.items.count(), 1)
        self.assertEqual(invoice.invoice_number, "INV-20990101-0001")
        self.assertEqual(session.get("cart"), {})
        self.assertNotIn("pending_invoice_number", session)
        self.assertEqual(invoice.payment_status, SalesInvoice.PAYMENT_PARTIAL)
        self.assertEqual(StockMovement.objects.filter(sales_invoice=invoice).count(), 1)
        self.assertEqual(invoice.antibiotic_entries.count(), 1)

    def test_main_pages_render_for_staff_user(self):
        self.client.force_login(self.user)
        for name in [
            "home",
            "order",
            "dashboard",
            "products",
            "customers",
            "suppliers",
            "invoices",
            "returns",
            "antibiotic_registers",
            "reminders",
            "settings",
        ]:
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)

    def test_product_search_api_returns_batch_suggestions(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("api_product_search"), {"q": "amo"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["batch_number"], "A-001")

    def test_product_variant_api_groups_strength_batches(self):
        second_product = Product.objects.create(name="Amoxicillin", generic_name="Amoxicillin", strength="250mg")
        ProductBatch.objects.create(
            product=second_product,
            batch_number="A-002",
            expiry_date=timezone.localdate() + timedelta(days=180),
            buy_price=Decimal("6.00"),
            tp_price=Decimal("8.00"),
            mrp=Decimal("10.00"),
            stock_quantity=5,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("api_product_variants", args=[self.product.pk]))
        self.assertEqual(response.status_code, 200)
        strengths = {item["strength"] for item in response.json()["variants"]}
        self.assertEqual(strengths, {"250mg", "500mg"})
