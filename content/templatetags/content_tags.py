import json
from urllib.parse import urlparse

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

# Schémas d'URL autorisés pour les liens et médias
_SAFE_URL_SCHEMES = {'http', 'https', '/'}


@register.simple_tag
def absolute_url(url, base):
    """Préfixe `url` avec `base` si elle n'est pas déjà absolue (image legacy,
    article d'une section à domaine autonome — voir newsletter_views._annotate_image_urls)."""
    if not url:
        return ''
    if url.startswith('http'):
        return url
    return f'{base}{url}'


def _safe_url(url):
    """
    Valide une URL : accepte http(s) et chemins relatifs.
    Rejette javascript:, data: et tout autre schéma dangereux.
    """
    url = (url or '').strip()
    if not url:
        return ''
    parsed = urlparse(url)
    if parsed.scheme and parsed.scheme not in ('http', 'https'):
        return ''
    return url


def _render_block(block):
    btype = block.get('type', '')
    data = block.get('data', {})

    if btype == 'paragraph':
        text = escape(data.get('text', ''))
        return f'<p>{text}</p>\n'

    if btype == 'header':
        try:
            level = max(1, min(6, int(data.get('level', 2))))
        except (ValueError, TypeError):
            level = 2
        text = escape(data.get('text', ''))
        return f'<h{level}>{text}</h{level}>\n'

    if btype == 'list':
        style = data.get('style', 'unordered')
        tag = 'ul' if style == 'unordered' else 'ol'
        items = data.get('items', [])
        items_html = ''.join(f'<li>{escape(item)}</li>' for item in items if isinstance(item, str))
        return f'<{tag}>{items_html}</{tag}>\n'

    if btype == 'quote':
        text = escape(data.get('text', ''))
        caption = escape(data.get('caption', ''))
        cite = f'<cite>— {caption}</cite>' if caption else ''
        return f'<blockquote><p>{text}</p>{cite}</blockquote>\n'

    if btype == 'code':
        code = escape(data.get('code', ''))
        return f'<pre><code>{code}</code></pre>\n'

    if btype == 'delimiter':
        return '<hr>\n'

    if btype == 'image':
        file_data = data.get('file', {})
        url = _safe_url(file_data.get('url', ''))
        caption = escape(data.get('caption', ''))
        classes = ['wp-block-image']
        if data.get('stretched'):
            classes.append('alignfull')
        elif data.get('withBackground'):
            classes.append('with-background')
        class_str = escape(' '.join(classes))
        caption_html = f'<figcaption>{caption}</figcaption>' if caption else ''
        if not url:
            return ''
        return f'<figure class="{class_str}"><img src="{escape(url)}" alt="{caption}"/>{caption_html}</figure>\n'

    if btype == 'gallery':
        images = data.get('images', [])
        try:
            columns = max(1, min(9, int(data.get('columns', 3))))
        except (ValueError, TypeError):
            columns = 3
        items_html = ''
        for img in images:
            url = _safe_url(img.get('url', ''))
            cap = escape(img.get('caption', ''))
            if not url:
                continue
            cap_html = f'<figcaption>{cap}</figcaption>' if cap else ''
            items_html += (
                f'<li class="blocks-gallery-item">'
                f'<figure><img src="{escape(url)}" alt="{cap}"/>{cap_html}</figure>'
                f'</li>'
            )
        return (
            f'<figure class="wp-block-gallery columns-{columns} is-cropped">'
            f'<ul class="blocks-gallery-grid">{items_html}</ul>'
            f'</figure>\n'
        )

    if btype == 'embed':
        embed_url = _safe_url(data.get('embed', ''))
        caption = escape(data.get('caption', ''))
        cap_html = f'<figcaption>{caption}</figcaption>' if caption else ''
        if not embed_url:
            return ''
        return (
            f'<figure class="wp-block-embed">'
            f'<div class="wp-block-embed__wrapper">'
            f'<iframe src="{escape(embed_url)}" frameborder="0" allowfullscreen style="width:100%;aspect-ratio:16/9;"></iframe>'
            f'</div>{cap_html}</figure>\n'
        )

    if btype == 'table':
        rows = data.get('content', [])
        with_headings = data.get('withHeadings', False)
        rows_html = ''
        for i, row in enumerate(rows):
            if not isinstance(row, list):
                continue
            cell_tag = 'th' if (i == 0 and with_headings) else 'td'
            cells = ''.join(f'<{cell_tag}>{escape(str(cell))}</{cell_tag}>' for cell in row)
            rows_html += f'<tr>{cells}</tr>'
        return f'<div style="overflow-x:auto"><table>{rows_html}</table></div>\n'

    if btype == 'file':
        url = _safe_url(data.get('url', ''))
        name = data.get('name', '')
        title = escape(data.get('title', '') or name)
        if not url:
            return ''
        return (
            f'<div class="wp-block-file">'
            f'<a href="{escape(url)}" class="wp-block-file__button" download>'
            f'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:.4rem;">'
            f'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
            f'<polyline points="14 2 14 8 20 8"/>'
            f'<line x1="12" y1="12" x2="12" y2="19"/><line x1="9" y1="16" x2="15" y2="16"/>'
            f'</svg>'
            f'{title}</a>'
            f'</div>\n'
        )

    # Bloc inconnu : ignorer silencieusement
    return ''


@register.filter(is_safe=True)
def render_content(content):
    """
    Rendu du contenu d'un article legacy (EditorJS JSON ou HTML WordPress importé).
    NOTE : ce filtre n'est plus utilisé dans les templates principaux (migré vers
    {{ article.body }} Wagtail StreamField). Conservé pour rétrocompatibilité.
    """
    if not content:
        return ''
    content = content.strip()

    if not content.startswith('{'):
        # HTML WordPress brut (contenu de confiance importé par admin uniquement)
        return mark_safe(content)

    try:
        data = json.loads(content)
        blocks = data.get('blocks', [])
        html = ''.join(_render_block(b) for b in blocks)
        return mark_safe(html)
    except (json.JSONDecodeError, KeyError, TypeError):
        return mark_safe(escape(content))
