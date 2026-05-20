from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pharmacy", "0005_alter_productbatch_batch_number"),
    ]

    operations = [
        migrations.AddField(
            model_name="appsetting",
            name="default_label_copies",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="appsetting",
            name="label_height_mm",
            field=models.PositiveIntegerField(default=20),
        ),
        migrations.AddField(
            model_name="appsetting",
            name="label_printer_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="appsetting",
            name="label_width_mm",
            field=models.PositiveIntegerField(default=20),
        ),
        migrations.AddField(
            model_name="appsetting",
            name="receipt_paper_chars",
            field=models.PositiveIntegerField(default=46),
        ),
        migrations.AddField(
            model_name="appsetting",
            name="receipt_printer_name",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
