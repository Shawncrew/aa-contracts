# aa-contracts stores no data of its own (it reads corptools' tables), so there
# are no models to register in the Django admin. Permissions live on the
# managed=False General model in models.py and are assigned like any other AA
# permission.
