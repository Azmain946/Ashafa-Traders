from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pharmacy", "0007_uploadeddocument_notes_optional_file"),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField(unique=True)),
                ("last_number", models.PositiveIntegerField(default=0)),
            ],
            options={
                "ordering": ["-date"],
            },
        ),
    ]
