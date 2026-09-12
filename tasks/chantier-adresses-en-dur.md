# Adresses du CMS écrites en dur — à reprendre

Noté le 12/09/2026 à la demande d'Arnaud, **sans urgence** : aucun effet visible
pour les rédacteurs, aucun lien avec la bascule.

## Le défaut

L'adresse des écrans d'édition est recopiée en toutes lettres à 83 endroits,
au lieu d'être demandée à Django. Exemple, `templates/cms/dashboard/site_panel.html` :

```html
<a href="/cms/snippets/cms/articlepage/add/">+ Nouvel article</a>
```

Le jour où cette adresse change — renommage de l'application, nouvelle
disposition de Wagtail, préfixe raccourci — ces liens mènent à une page
inexistante **sans que rien ne prévienne**.

Le pire cas est dans `cms/wagtail_hooks.py` : quatre sélecteurs CSS
reconnaissent le bouton « Nouvel article » **à son adresse**
(`a.w-header-button[href$="…/articlepage/add/"]`). Si elle change, le bouton
perd sa couleur : aucune erreur, aucun test rouge. Même famille que les 1 487
« > » restés un mois en ligne.

## Où c'est

| Gabarits | Occurrences |
|---|---|
| `templates/cms/dashboard/site_panel.html` | 12 |
| `templates/cms/menus/menu_tree.html` | 3 |
| `templates/cms/menus/_menu_item_row.html` | 2 |
| `templates/cms/dashboard/site_selector_sidebar.html` | 2 |
| `templates/content/stucs/agenda.html` | 2 |
| `templates/content/site_agenda_events.html` | 2 |
| `templates/cms/dashboard/syndicats.html` | 1 |
| `templates/content/newsletter_send.html` | 1 |

| Code | Occurrences |
|---|---|
| `content/newsletter_views.py` | 7 |
| `cms/wagtail_hooks.py` | 4 |
| `cms/models.py` | 1 |

| Tests | Occurrences |
|---|---|
| `cms/tests.py` | 32 |
| `content/tests.py` | 13 |
| `cms/tests_cloisonnement.py` | 1 |

## Le remède

- dans les gabarits : `{% url 'wagtailsnippets_cms_articlepage:add' %}` — si le
  nom de l'écran disparaît, la page plante tout de suite, au lieu de laisser un
  lien mort ;
- dans les tests : `reverse('wagtailsnippets_cms_articlepage:edit', args=[pk])` ;
- pour le bouton : le reconnaître autrement que par son adresse (une classe ou
  un attribut posé par le viewset), puis **vérifier par mutation** que le test
  du décor rougit si la règle CSS disparaît ;
- la bonne façon est déjà employée dans `cms/models.py`
  (`ArticlePage.get_cms_edit_url`) et dans `cms/wagtail_hooks.py` ligne 324.

## Ensuite, si on veut

Une fois les adresses calculées, raccourcir le chemin ne coûte plus qu'une
ligne par écran : `url_prefix = "articles"` sur le viewset donnerait
`/cms/articles/edit/1803/` au lieu de `/cms/snippets/cms/articlepage/edit/1803/`
(le « cms » en double vient du nom de l'application). Le nom interne utilisé par
`reverse()` ne bouge pas. Prévoir alors une redirection depuis l'ancien chemin :
Wagtail n'en pose aucune, et les favoris des rédacteurs casseraient.
