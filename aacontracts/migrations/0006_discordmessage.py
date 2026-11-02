from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aacontracts', '0005_globalconfig_shortage_message_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='DiscordMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('section', models.CharField(db_index=True, max_length=64)),
                ('seq', models.PositiveIntegerField(default=0)),
                ('message_id', models.BigIntegerField()),
            ],
            options={
                'ordering': ['section', 'seq'],
                'unique_together': {('section', 'seq')},
            },
        ),
    ]
