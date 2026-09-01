"""Range trois défauts de l'arbre des catégories confédérales.

Relevés sur les données de PRODUCTION le 01/09/2026 — et seulement ceux-là.
Ma note de chantier annonçait « 64 recopies à dédoublonner » : c'était faux, et
agir dessus aurait abîmé le 13. Les cinq groupes homonymes de ce syndicat
(« Vos droits » ×6, « Revendiquons ! » ×7, « Actualités - luttes » ×5…) ne sont
pas des doublons mais sa taxonomie par secteur, héritée de WordPress : chaque
rubrique appartient à un secteur, porte son propre slug et ses propres
articles. Cette commande n'y touche pas.

Restent trois défauts francs, tous sur la confédération :

1. **Deux « Gard »**, seul vrai doublon du réseau.
       pk 76  slug `gard`                   parent Syndicalisme       4 articles
       pk 77  slug `gard-cnt-so-occitanie`  parent CNT-SO Occitanie   1 article
   On garde celui qui a le slug propre et les articles, on le range sous
   « CNT-SO Occitanie » — le Gard est un département d'Occitanie, pas un
   secteur d'activité — et on lui reverse l'article du second.

2. **Un niveau intermédiaire vide** : « Syndicat national des transports et de
   l'aménagement du territoire », 0 article, dont l'unique raison d'être est de
   porter « Transport - logistique » (4 articles). C'est un nom de syndicat
   glissé au milieu de noms de métiers. On rattache l'enfant à
   « Syndicalisme » et on retire le niveau.

3. **STAA rangé sous STUCS.** « Syndicat des Travailleur.euse.s
   Artistes-Auteurs (STAA) » (6 articles) est enfant de « Syndicat des
   travailleur·euses uni·es de la culture et du spectacle (STUCS) »
   (32 articles). Ce sont deux syndicats distincts — le STAA a même son propre
   site. On le rattache à « Syndicalisme ».

Aucun article n'est supprimé : ils sont reversés avant que la catégorie ne
disparaisse, et la commande refuse d'agir si le compte final ne correspond pas.

Usage :
    python manage.py range_categories_conf              # constat seul (défaut)
    python manage.py range_categories_conf --appliquer
"""
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = ("Fusionne les deux « Gard » de la conf, retire le niveau "
            "« Syndicat national des transports » et sort le STAA de sous le STUCS")

    def add_arguments(self, parser):
        parser.add_argument(
            '--appliquer', action='store_true',
            help="Écrit en base. Sans ce drapeau, la commande n'affiche que ce "
                 "qu'elle ferait.")

    def handle(self, *args, **options):
        from cms.models import CmsCategory

        appliquer = options['appliquer']
        self.stdout.write(self.style.MIGRATE_HEADING(
            "Rangement des catégories confédérales — "
            + ("ÉCRITURE EN BASE" if appliquer else "constat seul (--appliquer pour écrire)")))

        conf = CmsCategory.objects.filter(section_slug='principal')
        actions, avertissements = [], []

        def par_nom(nom):
            return list(conf.filter(name=nom))

        # ── 1. les deux Gard ──────────────────────────────────────────────────
        gards = sorted(par_nom('Gard'), key=lambda c: -c.articles.count())
        if len(gards) == 2:
            garde, absorbe = gards
            occitanie = conf.filter(name='CNT-SO Occitanie', parent__isnull=True).first()
            actions.append((
                f"Gard : garder pk={garde.pk} (slug « {garde.slug} », "
                f"{garde.articles.count()} articles), lui reverser les "
                f"{absorbe.articles.count()} de pk={absorbe.pk}, "
                f"le ranger sous « CNT-SO Occitanie », supprimer pk={absorbe.pk}",
                lambda g=garde, a=absorbe, o=occitanie: self._fusionner(g, a, o),
            ))
        elif len(gards) > 2:
            avertissements.append(f"{len(gards)} catégories « Gard » : cas non prévu, rien fait")
        else:
            avertissements.append("Gard : un seul ou aucun — déjà rangé")

        # ── 2. le niveau vide des transports ─────────────────────────────────
        niveau = conf.filter(name__startswith='Syndicat national des transports').first()
        syndicalisme = conf.filter(name='Syndicalisme', parent__isnull=True).first()
        if niveau and syndicalisme:
            enfants = list(conf.filter(parent=niveau))
            if niveau.articles.exists():
                avertissements.append(
                    f"« {niveau.name[:40]} » porte des articles : non supprimé")
            else:
                actions.append((
                    f"Transports : rattacher {[e.name for e in enfants]} à "
                    f"« Syndicalisme », puis supprimer le niveau vide pk={niveau.pk}",
                    lambda n=niveau, e=enfants, s=syndicalisme: self._retirer_niveau(n, e, s),
                ))
        else:
            avertissements.append("Niveau « Syndicat national des transports » : absent")

        # ── 3. le STAA sous le STUCS ─────────────────────────────────────────
        staa = conf.filter(name__contains='(STAA)').first()
        if staa and syndicalisme and staa.parent_id and staa.parent_id != syndicalisme.pk:
            actions.append((
                f"STAA : le sortir de sous « {staa.parent.name[:34]} » "
                f"et le rattacher à « Syndicalisme »",
                lambda s=staa, sy=syndicalisme: self._reparenter(s, sy),
            ))
        else:
            avertissements.append("STAA : déjà rattaché, ou absent")

        for texte, _ in actions:
            self.stdout.write(f"  • {texte}")
        for texte in avertissements:
            self.stdout.write(self.style.WARNING(f"  ⚠ {texte}"))

        if not actions:
            self.stdout.write(self.style.SUCCESS("Rien à faire."))
            return
        if not appliquer:
            self.stdout.write(self.style.NOTICE(
                f"\n{len(actions)} action(s) — relancer avec --appliquer pour écrire."))
            return

        avant = self._articles_categorises(CmsCategory)
        with transaction.atomic():
            for _, faire in actions:
                faire()
            apres = self._articles_categorises(CmsCategory)
            if apres < avant:
                raise RuntimeError(
                    f"ARRÊT : {avant - apres} article(s) se retrouvent sans "
                    f"aucune catégorie ({avant} → {apres}). Transaction annulée.")
        self.stdout.write(self.style.SUCCESS(
            f"Appliqué. Articles rattachés à au moins une catégorie : "
            f"{avant} → {apres}."))

    # ── opérations ───────────────────────────────────────────────────────────

    @staticmethod
    def _articles_categorises(CmsCategory):
        """Combien d'articles portent AU MOINS une catégorie, tous sites.

        C'est le filet, et c'est le bon invariant. Le premier que j'avais écrit
        comptait les *liens* : il refusait la fusion dès qu'un article
        appartenait aux deux « Gard », alors que voir ses deux liens n'en faire
        qu'un est exactement ce qu'on lui demande. Ce qu'il faut interdire, ce
        n'est pas la perte d'un lien, c'est qu'un article se retrouve sans
        aucune catégorie — il disparaîtrait alors de toutes les pages de
        rubrique, de l'accueil et de la newsletter.
        """
        return (CmsCategory.articles.through.objects
                .values('articlepage_id').distinct().count())

    def _fusionner(self, garde, absorbe, nouveau_parent):
        lien = garde.articles.through
        champ_cat = 'cmscategory_id'
        attendu = set(lien.objects.filter(
            **{f'{champ_cat}__in': [garde.pk, absorbe.pk]}
        ).values_list('articlepage_id', flat=True))
        for row in lien.objects.filter(**{champ_cat: absorbe.pk}):
            # `get_or_create` : un article rattaché aux DEUX Gard ne doit pas
            # produire de doublon de liaison, que la contrainte refuserait.
            lien.objects.get_or_create(
                articlepage_id=row.articlepage_id, **{champ_cat: garde.pk})
            row.delete()
        if lien.objects.filter(**{champ_cat: absorbe.pk}).exists():
            raise RuntimeError(
                f"ARRÊT : des articles restent liés à pk={absorbe.pk}")
        obtenu = set(lien.objects.filter(**{champ_cat: garde.pk})
                     .values_list('articlepage_id', flat=True))
        if obtenu != attendu:
            raise RuntimeError(
                f"ARRÊT : la fusion devait réunir {len(attendu)} articles, "
                f"elle en compte {len(obtenu)}")
        if nouveau_parent is not None:
            garde.parent = nouveau_parent
            garde.save(update_fields=['parent'])
        absorbe.delete()

    def _retirer_niveau(self, niveau, enfants, nouveau_parent):
        for enfant in enfants:
            enfant.parent = nouveau_parent
            enfant.save(update_fields=['parent'])
        niveau.delete()

    def _reparenter(self, categorie, nouveau_parent):
        categorie.parent = nouveau_parent
        categorie.save(update_fields=['parent'])
