from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0006_gmailprocessedmessage_log_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="gmailprocessedmessage",
            name="fetch_attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
