from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aacontracts', '0004_alter_globalconfig_price_basis'),
    ]

    operations = [
        migrations.AddField(
            model_name='globalconfig',
            name='shortage_message_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
