from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Order, Product, ProductBatch, ProductCategory, SalesInvoice, StockMovement
from .services import add_or_update_cart_item, create_order_update_invoice, finalize_checkout, lookup_return_invoice, process_return


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
        session["pending_order_number"] = "2099010101"
        add_or_update_cart_item(session, self.batch.id, quantity=2, discount_percent=Decimal("10.00"))

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
        self.assertEqual(invoice.order.order_number, "2099010101")
        self.assertEqual(invoice.invoice_number, "20990101011")
        self.assertEqual(invoice.items.first().discount_percent, Decimal("10.00"))
        self.assertEqual(invoice.subtotal, Decimal("25.20"))
        self.assertEqual(invoice.round_off_amount, Decimal("0.20"))
        self.assertEqual(invoice.grand_total, Decimal("25.00"))
        self.assertEqual(session.get("cart"), {})
        self.assertNotIn("pending_order_number", session)
        self.assertEqual(invoice.payment_status, SalesInvoice.PAYMENT_PARTIAL)
        self.assertEqual(invoice.order.payment_status, Order.PAYMENT_PARTIAL)
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

    def test_batch_label_page_and_qr_png(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("batch_barcode_print", args=[self.batch.pk]), {"labels": 2})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Print with QZ Tray")
        from io import BytesIO

        from PIL import Image

        from pharmacy.printing import build_label_qr_payload, parse_label_qr_payload

        payload = build_label_qr_payload(self.batch)
        self.assertEqual(len(payload), 13)
        self.assertTrue(payload.isdigit())
        self.assertEqual(int(payload), self.batch.pk)
        parsed = parse_label_qr_payload(payload)
        self.assertEqual(parsed["entry_id"], str(self.batch.pk))

        qr_response = self.client.get(reverse("api_batch_qr_png", args=[self.batch.pk]))
        self.assertEqual(qr_response.status_code, 200)
        self.assertEqual(qr_response["Content-Type"], "image/png")
        qr_image = Image.open(BytesIO(qr_response.content))
        self.assertEqual(qr_image.size, (50, 50))
        pixels = set(qr_image.getdata())
        self.assertTrue(pixels & {0, 1} or pixels & {(0, 0, 0), (255, 255, 255)})

    def test_qz_signing_endpoints(self):
        self.client.force_login(self.user)
        cert = self.client.get(reverse("api_qz_certificate"))
        self.assertEqual(cert.status_code, 200)
        self.assertIn("BEGIN CERTIFICATE", cert.content.decode())
        sign = self.client.get(reverse("api_qz_sign"), {"request": "test-message"})
        self.assertEqual(sign.status_code, 200)
        self.assertGreater(len(sign.content), 20)

    def test_printer_settings_and_receipt_api(self):
        from pharmacy.models import AppSetting
        from pharmacy.printing import build_receipt_escpos, item_line

        self.client.force_login(self.user)
        settings = AppSetting.load()
        settings.receipt_printer_name = "Receipt-Test"
        settings.label_printer_name = "Label-Test"
        settings.save()
        get_response = self.client.get(reverse("api_printer_settings"))
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["receipt_printer_name"], "Receipt-Test")
        save_response = self.client.post(
            reverse("api_printer_settings_save"),
            data='{"receipt_printer_name":"POS-80","label_printer_name":"ZD410"}',
            content_type="application/json",
        )
        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(save_response.json()["settings"]["label_printer_name"], "ZD410")
        truncated = item_line("Napa Extra Super Long Medicine Name", 12, "999 BDT", "11988 BDT", line_chars=46)
        self.assertLessEqual(len(truncated), 46)
        session = SessionLike()
        session["pending_order_number"] = "2099010102"
        add_or_update_cart_item(session, self.batch.id, quantity=2, discount_percent=Decimal("0.00"))
        invoice = finalize_checkout(
            session,
            {
                "customer_name": "Receipt Test",
                "customer_phone": "01710000001",
                "discount_percent": Decimal("0.00"),
                "discount_amount": Decimal("0.00"),
                "paid_amount": Decimal("50.00"),
                "notes": "",
            },
            self.user,
        )
        receipt = build_receipt_escpos(invoice)
        self.assertIn(invoice.order.order_number, receipt)
        self.assertIn("\x1D\x56\x01", receipt)
        api_response = self.client.get(reverse("api_invoice_receipt", args=[invoice.pk]))
        self.assertEqual(api_response.status_code, 200)
        self.assertIn("receipt", api_response.json())

    def test_product_entry_accepts_optional_category_strength_and_batch_fields(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("product_create"),
            {
                "print_barcode": "1",
                "label_count": "2",
                "name": "Optional Entry",
                "generic_name": "Optional",
                "expiry_date": (timezone.localdate() + timedelta(days=180)).isoformat(),
                "number_of_boxes": "2",
                "units_per_box": "10",
                "buy_price_per_box": "80.00",
                "tp_price_per_box": "95.12",
                "mrp_per_box": "100.87",
            },
        )
        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(name="Optional Entry")
        batch = product.batches.first()
        self.assertEqual(product.strength, "")
        self.assertIsNone(product.category)
        self.assertTrue(batch.batch_number)
        self.assertIsNone(batch.mfg_date)

    def test_return_lookup_and_processing_creates_printable_invoice(self):
        session = SessionLike()
        session["pending_order_number"] = "2099010102"
        add_or_update_cart_item(session, self.batch.id, quantity=7)
        invoice = finalize_checkout(
            session,
            {
                "customer_name": "Return Customer",
                "customer_phone": "01710000001",
                "discount_percent": Decimal("0.00"),
                "discount_amount": Decimal("0.00"),
                "paid_amount": Decimal("98.00"),
                "notes": "",
            },
            self.user,
        )

        self.assertEqual(lookup_return_invoice(invoice.order.order_number).pk, invoice.pk)
        self.assertEqual(lookup_return_invoice(phone="01710000001").pk, invoice.pk)
        self.assertEqual(lookup_return_invoice(invoice_date=invoice.order.order_date).pk, invoice.pk)

        create_order_update_invoice(invoice.order, self.user)
        self.assertEqual(lookup_return_invoice(invoice.order.order_number).pk, invoice.pk)

        invoice.order = None
        invoice.save(update_fields=["order"])
        resolved = lookup_return_invoice("2099010102")
        self.assertEqual(resolved.pk, invoice.pk)
        self.assertEqual(resolved.order.order_number, "2099010102")
        invoice = resolved

        return_tx, new_invoice = process_return(invoice, {str(invoice.items.first().id): "3"}, user=self.user)
        self.assertEqual(return_tx.total_refund, Decimal("42.00"))
        self.assertEqual(new_invoice.order_id, invoice.order_id)
        self.assertEqual(new_invoice.items.first().quantity, 4)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.stock_quantity, 6)
