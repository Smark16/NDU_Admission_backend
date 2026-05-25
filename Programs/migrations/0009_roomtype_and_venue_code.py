from django.db import migrations, models

DEFAULT_TYPES = [
    "Lecture room",
    "Laboratory",
    "Hall / auditorium",
    "Office / seminar",
    "Other",
]

LEGACY_MAP = {
    "lecture": "Lecture room",
    "lab": "Laboratory",
    "practical": "Laboratory",
    "hall": "Hall / auditorium",
    "office": "Office / seminar",
    "other": "Other",
}


def seed_room_types(apps, schema_editor):
    RoomType = apps.get_model("Programs", "RoomType")
    Venue = apps.get_model("Programs", "Venue")
    for name in DEFAULT_TYPES:
        RoomType.objects.get_or_create(name=name, defaults={"is_active": True})
    for raw in Venue.objects.values_list("room_type", flat=True).distinct():
        label = LEGACY_MAP.get((raw or "").strip().lower(), (raw or "").strip())
        if label:
            RoomType.objects.get_or_create(name=label[:40], defaults={"is_active": True})
    for venue in Venue.objects.all():
        label = LEGACY_MAP.get((venue.room_type or "").strip().lower(), venue.room_type or "Other")
        if label:
            venue.room_type = label[:40]
            venue.save(update_fields=["room_type"])


class Migration(migrations.Migration):

    dependencies = [
        ("Programs", "0008_venue_classroom_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="RoomType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=40, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Room type",
                "verbose_name_plural": "Room types",
                "ordering": ["name"],
            },
        ),
        migrations.AlterField(
            model_name="venue",
            name="room_type",
            field=models.CharField(
                default="Lecture room",
                help_text="Label from room type registry (e.g. Lecture room, Laboratory).",
                max_length=40,
            ),
        ),
        migrations.RunPython(seed_room_types, migrations.RunPython.noop),
    ]
