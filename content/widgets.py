from django import forms
from django.utils.html import format_html, escape


EDITORJS_CDN = [
    'https://cdn.jsdelivr.net/npm/@editorjs/editorjs@2.28.2/dist/editorjs.umd.min.js',
    'https://cdn.jsdelivr.net/npm/@editorjs/header@2.8.1/dist/header.umd.min.js',
    'https://cdn.jsdelivr.net/npm/@editorjs/list@1.9.0/dist/list.umd.min.js',
    'https://cdn.jsdelivr.net/npm/@editorjs/quote@2.6.0/dist/quote.umd.min.js',
    'https://cdn.jsdelivr.net/npm/@editorjs/code@2.9.0/dist/code.umd.min.js',
    'https://cdn.jsdelivr.net/npm/@editorjs/delimiter@1.4.0/dist/delimiter.umd.min.js',
    'https://cdn.jsdelivr.net/npm/@editorjs/table@2.3.0/dist/table.umd.min.js',
    'https://cdn.jsdelivr.net/npm/@editorjs/inline-code@1.5.0/dist/inline-code.umd.min.js',
    'https://cdn.jsdelivr.net/npm/@editorjs/image@2.9.0/dist/image.umd.min.js',
    'https://cdn.jsdelivr.net/npm/@editorjs/embed@2.7.4/dist/embed.umd.min.js',
]


class EditorJsWidget(forms.Widget):
    """
    Widget Wagtail pour le champ content des articles/pages.
    Affiche Editor.js à la place d'un <textarea>.
    La valeur JSON est stockée dans un <input type="hidden">.
    """

    template_name = None  # on override render() directement

    def render(self, name, value, attrs=None, renderer=None):
        attrs = attrs or {}
        field_id = attrs.get('id') or f'id_{name}'
        safe_value = escape(value or '')

        return format_html(
            '<div class="editorjs-wrapper" data-field-id="{field_id}">'
            '<input type="hidden" name="{name}" id="{field_id}" value="{value}">'
            '<div class="editorjs-container"></div>'
            '</div>',
            field_id=field_id,
            name=name,
            value=safe_value,
        )

    def value_from_datadict(self, data, files, name):
        return data.get(name)

    class Media:
        extend = False
        js = EDITORJS_CDN + ['content/js/editorjs_wagtail.js']
        css = {'all': ['content/css/editorjs_wagtail.css']}
