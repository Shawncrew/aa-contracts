from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("aacontracts", "0010_fitting_alerts"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.AddField(
            model_name="globalconfig",
            name="fitting_ping_groups",
            field=models.ManyToManyField(
                blank=True, related_name="+", to="auth.group",
                verbose_name="Fitting update ping groups",
                help_text="Ping the same-named Discord roles on fitting updates. Leave empty to post quietly.",
            ),
        ),
    ]
