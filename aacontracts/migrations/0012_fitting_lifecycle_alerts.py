from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("aacontracts", "0011_fitting_ping_groups")]

    operations = [
        # Drop the cascading foreign key while preserving existing event IDs
        # and their original fitting IDs in the same database column.
        migrations.AlterField(
            model_name="fittingchange",
            name="fitting",
            field=models.PositiveBigIntegerField(db_column="fitting_id"),
        ),
        migrations.RenameField(
            model_name="fittingchange",
            old_name="fitting",
            new_name="fitting_id",
        ),
        migrations.AlterField(
            model_name="fittingchange",
            name="fitting_id",
            field=models.PositiveBigIntegerField(),
        ),
        migrations.AlterField(
            model_name="fittingchange",
            name="before",
            field=models.JSONField(null=True),
        ),
        migrations.AlterField(
            model_name="fittingchange",
            name="after",
            field=models.JSONField(null=True),
        ),
        migrations.AlterField(
            model_name="globalconfig",
            name="fitting_ping_groups",
            field=models.ManyToManyField(
                blank=True, related_name="+", to="auth.group",
                verbose_name="Fitting alert ping groups",
                help_text="Ping the same-named Discord roles when fits are added, updated, or removed. Leave empty to post quietly.",
            ),
        ),
    ]
