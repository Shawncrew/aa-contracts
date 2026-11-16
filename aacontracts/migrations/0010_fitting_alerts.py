import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("aacontracts", "0009_globalconfig_suppliers_group")]

    operations = [
        migrations.CreateModel(
            name="FittingSnapshot",
            fields=[
                ("fitting", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE, primary_key=True,
                    serialize=False, to="fittings.fitting",
                )),
                ("state", models.JSONField()),
            ],
        ),
        migrations.CreateModel(
            name="FittingChange",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("channel_id", models.PositiveBigIntegerField()),
                ("before", models.JSONField()),
                ("after", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("message_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("fitting", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="fittings.fitting")),
            ],
            options={
                "indexes": [models.Index(fields=["channel_id", "message_id", "id"], name="aac_fit_change_pending")],
            },
        ),
    ]
