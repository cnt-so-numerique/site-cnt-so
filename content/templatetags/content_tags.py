import json

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


def _render_block(block):
    btype = block.get('type', '')
    data = block.get('data', {})

    if btype == 'paragraph':
        text = data.get('text', '')
        return f'<p>{text}</p>\n'

    if btype == 'header':
        level = data.get('level', 2)
        text = data.get('text', '')
        return f'<h{level}>{text}</h{level}>\n'

    if btype == 'list':
        style = data.get('style', 'unordered')
        tag = 'ul' if style == 'unordered' else 'ol'
        items = data.get('items', [])
        items_html = ''.join(f'<li>{item}</li>' for item in items)
        return f'<{tag}>{items_html}</{tag}>\n'

    if btype == 'quote':
        text = data.get('text', '')
        caption = data.get('caption', '')
        cite = f'<cite>— {caption}</cite>' if caption else ''
        return f'<blockquote><p>{text}</p>{cite}</blockquote>\n'

    if btype == 'code':
        code = escape(data.get('code', ''))
        return f'<pre><code>{code}</code></pre>\n'

    if btype == 'delimiter':
        return '<hr>\n'

    if btype == 'image':
        file_data = data.get('file', {})
        url = file_data.get('url', '')
        caption = data.get('caption', '')
        classes = ['wp-block-image']
        if data.get('stretched'):
            classes.append('alignfull')
        elif data.get('withBackground'):
            classes.append('with-background')
        class_str = ' '.join(classes)
        caption_html = f'<figcaption>{caption}</figcaption>' if caption else ''
        return f'<figure class="{class_str}"><img src="{url}" alt="{escape(caption)}"/>{caption_html}</figure>\n'

    if btype == 'gallery':
        images = data.get('images', [])
        columns = data.get('columns', 3)
        items_html = ''
        for img in images:
            url = img.get('url', '')
            cap = img.get('caption', '')
            cap_html = f'<figcaption>{cap}</figcaption>' if cap else ''
            items_html += f'<li class="blocks-gallery-item"><figure><img src="{url}" alt="{escape(cap)}"/>{cap_html}</figure></li>'
        return (
            f'<figure class="wp-block-gallery columns-{columns} is-cropped">'
            f'<ul class="blocks-gallery-grid">{items_html}</ul>'
            f'</figure>\n'
        )

    if btype == 'embed':
        embed_url = data.get('embed', '')
        caption = data.get('caption', '')
        cap_html = f'<figcaption>{caption}</figcaption>' if caption else ''
        return (
            f'<figure class="wp-block-embed">'
            f'<div class="wp-block-embed__wrapper">'
            f'<iframe src="{embed_url}" frameborder="0" allowfullscreen style="width:100%;aspect-ratio:16/9;"></iframe>'
            f'</div>{cap_html}</figure>\n'
        )

    if btype == 'table':
        rows = data.get('content', [])
        with_headings = data.get('withHeadings', False)
        rows_html = ''
        for i, row in enumerate(rows):
            cell_tag = 'th' if (i == 0 and with_headings) else 'td'
            cells = ''.join(f'<{cell_tag}>{cell}</{cell_tag}>' for cell in row)
            rows_html += f'<tr>{cells}</tr>'
        return f'<div style="overflow-x:auto"><table>{rows_html}</table></div>\n'

    if btype == 'file':
        url = data.get('url', '')
        name = data.get('name', '')
        title = data.get('title', '') or name
        if not url:
            return ''
        return (
            f'<div class="wp-block-file">'
            f'<a href="{url}" class="wp-block-file__button" download>'
            f'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:.4rem;">'
            f'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
            f'<polyline points="14 2 14 8 20 8"/>'
            f'<line x1="12" y1="12" x2="12" y2="19"/><line x1="9" y1="16" x2="15" y2="16"/>'
            f'</svg>'
            f'{escape(title)}</a>'
            f'</div>\n'
        )

    # Bloc inconnu : ignorer silencieusement
    return ''


@register.filter(is_safe=True)
def render_content(content):
    """
    Rendu du contenu d'un article.
    - Si JSON EditorJS → convertit chaque bloc en HTML
    - Si HTML WordPress (import) → retourne tel quel
    """
    if not content:
        return ''
    content = content.strip()

    if not content.startswith('{'):
        # HTML WordPress brut
        return mark_safe(content)

    try:
        data = json.loads(content)
        blocks = data.get('blocks', [])
        html = ''.join(_render_block(b) for b in blocks)
        return mark_safe(html)
    except (json.JSONDecodeError, KeyError, TypeError):
        # En cas d'erreur de parsing, afficher tel quel
        return mark_safe(content)
