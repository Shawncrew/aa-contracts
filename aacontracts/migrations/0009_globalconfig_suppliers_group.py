from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('aacontracts', '0008_location_min_markup_percent'),
    ]

    operations = [
        migrations.AddField(
            model_name='globalconfig',
            name='suppliers_group',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='+', to='auth.group',
                help_text='Auth group whose members are the suppliers listed on the Participation tab '
                          '(ranked by contracts up, including those with none). Falls back to the ping group.',
            ),
        ),
    ]
