from django import forms
from django.utils.html import escape, format_html, mark_safe


class OVHMailingListWidget(forms.Widget):
    """
    Widget multi-sélection pour les listes mails OVH.
    Stocke les noms sélectionnés sous forme de chaîne séparée par des virgules.
    Les choix sont chargés dynamiquement depuis l'API OVH à chaque rendu.
    """

    def _load_choices(self):
        try:
            from cms.ovh_client import list_mailing_lists
            return sorted(list_mailing_lists())
        except Exception:
            return None  # None = erreur API

    def format_value(self, value):
        if not value:
            return set()
        return {v.strip() for v in value.split(',') if v.strip()}

    def value_from_datadict(self, data, files, name):
        selected = data.getlist(name)
        return ','.join(selected)

    def render(self, name, value, attrs=None, renderer=None):
        selected = self.format_value(value)
        choices = self._load_choices()

        if choices is None:
            hidden = format_html('<input type="hidden" name="{}" value="{}">', name, value or '')
            return format_html(
                '<div style="border:1px solid #fca5a5;border-radius:6px;padding:.75rem 1rem;background:#fef2f2;color:#b91c1c;font-size:.875rem;">'
                '⚠️ Impossible de charger les listes OVH (vérifiez la connexion API).'
                '{}</div>',
                hidden
            )

        if not choices:
            return format_html(
                '<div style="border:1px solid #e5e7eb;border-radius:6px;padding:.75rem 1rem;background:#f9fafb;color:#6b7280;font-size:.875rem;">'
                'Aucune liste OVH disponible.'
                '</div>'
            )

        items = []
        for list_name in choices:
            checked = 'checked' if list_name in selected else ''
            bg = 'background:#fde8ea;' if list_name in selected else ''
            items.append(format_html(
                '<label style="display:flex;align-items:center;gap:.6rem;cursor:pointer;font-size:.9rem;'
                'padding:.35rem .5rem;border-radius:4px;{bg}">'
                '<input type="checkbox" name="{name}" value="{val}" {checked} '
                'style="width:15px;height:15px;accent-color:#e63946;">'
                '<span style="font-family:monospace;font-size:.875rem;">{val}</span>'
                '<span style="color:#9ca3af;font-size:.8rem;">@cnt-so.info</span>'
                '</label>',
                bg=mark_safe(bg), name=name, val=list_name, checked=mark_safe(checked)
            ))

        inner = mark_safe(''.join(str(i) for i in items))
        note = '' if selected else mark_safe(
            '<p style="margin:.5rem 0 0;font-size:.8rem;color:#9ca3af;">Aucune liste sélectionnée.</p>'
        )

        return format_html(
            '<div style="border:1px solid #e5e7eb;border-radius:6px;padding:.75rem 1rem;'
            'background:#f9fafb;max-width:480px;display:flex;flex-direction:column;gap:.1rem;">'
            '{}{}</div>',
            inner, note
        )
