from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aacontracts', '0007_fitalert_main_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='location',
            name='min_markup_percent',
            field=models.DecimalField(
                decimal_places=2, default=Decimal('0'), max_digits=6,
                help_text='Minimum markup % at this location. The effective markup is the '
                          'greater of this and the global markup, so remote stations can be '
                          'priced higher. 0 = just use the global markup.',
            ),
        ),
    ]
