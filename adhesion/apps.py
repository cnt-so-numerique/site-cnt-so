from django.apps import AppConfig


class AdhesionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'adhesion'
    verbose_name = "Adhésions"

    def ready(self):
        import adhesion.signals  # noqa
