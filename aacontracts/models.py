"""aa-contracts holds no data of its own — it reads corptools' contract tables.

This model exists only to own the app's permissions (managed = False, so no
table is created).
"""
from django.db import models


class General(models.Model):
    class Meta:
        managed = False
        default_permissions = ()
        permissions = (
            ("view_contracts", "Can view the alliance contracts dashboard"),
            ("manage_contracts", "Can see every alliance contracts setting and detail"),
        )
