import json
from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def render_editorjs(content):
    """Rend le contenu Editor.js (JSON) ou HTML legacy en HTML."""
    if not content:
        return ''

    content = content.strip()

    # Contenu HTML legacy (WordPress import)
    if not content.startswith('{'):
        return mark_safe(content)

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return mark_safe(content)

    blocks = data.get('blocks', [])
    html_parts = []

    for block in blocks:
        btype = block.get('type', '')
        bdata = block.get('data', {})

        if btype == 'paragraph':
            text = bdata.get('text', '')
            html_parts.append(f'<p>{text}</p>')

        elif btype == 'header':
            level = bdata.get('level', 2)
            text = bdata.get('text', '')
            html_parts.append(f'<h{level}>{text}</h{level}>')

        elif btype == 'list':
            style = bdata.get('style', 'unordered')
            items = bdata.get('items', [])
            tag = 'ul' if style == 'unordered' else 'ol'
            items_html = ''.join(f'<li>{item}</li>' for item in items)
            html_parts.append(f'<{tag}>{items_html}</{tag}>')

        elif btype == 'quote':
            text = bdata.get('text', '')
            caption = bdata.get('caption', '')
            cite = f'<cite>{caption}</cite>' if caption else ''
            html_parts.append(f'<blockquote>{text}{cite}</blockquote>')

        elif btype == 'code':
            code = escape(bdata.get('code', ''))
            html_parts.append(f'<pre><code>{code}</code></pre>')

        elif btype == 'delimiter':
            html_parts.append('<hr>')

        elif btype == 'image':
            url = bdata.get('file', {}).get('url', '')
            caption = bdata.get('caption', '')
            alt = caption or ''
            stretched = 'image--stretched' if bdata.get('stretched') else ''
            html_parts.append(
                f'<figure class="image {stretched}">'
                f'<img src="{url}" alt="{escape(alt)}">'
                f'{"<figcaption>" + caption + "</figcaption>" if caption else ""}'
                f'</figure>'
            )

        elif btype == 'table':
            rows = bdata.get('content', [])
            rows_html = ''
            for i, row in enumerate(rows):
                cells = ''.join(
                    f'<th>{cell}</th>' if i == 0 else f'<td>{cell}</td>'
                    for cell in row
                )
                rows_html += f'<tr>{cells}</tr>'
            html_parts.append(f'<table>{rows_html}</table>')

        elif btype == 'embed':
            embed_url = bdata.get('embed', '')
            caption = bdata.get('caption', '')
            service = bdata.get('service', '')
            width = bdata.get('width', '100%')
            height = bdata.get('height', 400)
            html_parts.append(
                f'<figure class="embed embed--{service}" style="margin:1.5rem 0;">'
                f'<div style="position:relative;padding-bottom:56.25%;height:0;overflow:hidden;">'
                f'<iframe src="{embed_url}" frameborder="0" allowfullscreen '
                f'style="position:absolute;top:0;left:0;width:100%;height:100%;border-radius:8px;"></iframe>'
                f'</div>'
                f'{"<figcaption style=\'font-size:.85rem;color:#94a3b8;margin-top:.5rem;text-align:center;\'>" + escape(caption) + "</figcaption>" if caption else ""}'
                f'</figure>'
            )

        elif btype == 'warning':
            title = bdata.get('title', '')
            message = bdata.get('message', '')
            html_parts.append(
                f'<div class="warning">'
                f'{"<strong>" + title + "</strong>" if title else ""}'
                f'<p>{message}</p>'
                f'</div>'
            )

    return mark_safe('\n'.join(html_parts))
