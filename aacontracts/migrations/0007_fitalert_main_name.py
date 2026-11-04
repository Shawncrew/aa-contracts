from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aacontracts', '0006_discordmessage'),
    ]

    operations = [
        migrations.AddField(
            model_name='fitalert',
            name='main_name',
            field=models.CharField(blank=True, max_length=128),
        ),
    ]
