from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="General",
            fields=[
                (
                    "id",
                    models.AutoField(
                        primary_key=True, serialize=False, auto_created=True
                    ),
                ),
            ],
            options={
                "managed": False,
                "default_permissions": (),
                "permissions": (
                    ("view_contracts", "Can view the alliance contracts dashboard"),
                    (
                        "manage_contracts",
                        "Can see every alliance contracts setting and detail",
                    ),
                ),
            },
        ),
    ]
