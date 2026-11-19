"""Carte interne des implantations des syndicats (/cms/implantations/).

Réservée aux comptes qui ont `cms.acceder_carte_implantations` — en pratique
le groupe « Carte des implantations » (content/apps.py), plus les
superutilisateurs. Être rédacteur en chef ne suffit pas : la carte porte des
lieux et des téléphones de camarades, on la donne à quelques personnes.

Les données partent vers le navigateur par `json_script` et les bulles sont
construites en DOM (`textContent`) : un nom ou une note contenant du HTML
s'affiche tel quel, il n'est jamais interprété.
"""
from collections import Counter

from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from cms.models import Implantation, SectionPage
from content.admin_utils import WagtailChefRequiredMixin

PERMISSION = 'cms.acceder_carte_implantations'

#: Une couleur par syndicat, dans l'ordre alphabétique. Teintes distinctes
#: lisibles sur fond de carte clair ; au-delà, on repart du début.
COULEURS = [
    '#d62728', '#1f77b4', '#2ca02c', '#9467bd', '#ff7f0e', '#17becf',
    '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#393b79', '#637939',
    '#843c39', '#7b4173', '#3182bd', '#e6550d',
]

TYPES_SUGGERES = [
    'Local syndical', 'Section syndicale', 'Adhérent·es sans section', 'Permanence',
]


def cle(texte):
    """Clé de regroupement : « Amazon », « amazon » et « Amazon  » ne font qu'un."""
    return ' '.join((texte or '').split()).casefold()


def libelles(valeurs):
    """{clé: libellé} — le libellé est la graphie la plus fréquente ; à égalité,
    celle qui a des majuscules (« Amazon » plutôt que « amazon »)."""
    par_cle = {}
    for valeur in valeurs:
        if cle(valeur):
            par_cle.setdefault(cle(valeur), Counter())[' '.join(valeur.split())] += 1
    return {k: min(c, key=lambda v: (-c[v], v)) for k, c in par_cle.items()}


class AccesCarteMixin(WagtailChefRequiredMixin):
    """Connexion à l'admin + permission de la carte (pas le simple rôle de chef)."""

    def test_func(self):
        return self.request.user.has_perm(PERMISSION)


class ImplantationForm(forms.ModelForm):

    class Meta:
        model = Implantation
        fields = [
            'syndicat', 'nom', 'type_implantation', 'entreprise', 'adresse',
            'latitude', 'longitude', 'contact_nom', 'telephone', 'email', 'texte_libre',
        ]
        widgets = {
            'type_implantation': forms.TextInput(attrs={'list': 'types-connus'}),
            'entreprise': forms.TextInput(attrs={'list': 'entreprises-connues'}),
            'latitude': forms.NumberInput(attrs={'step': 'any'}),
            'longitude': forms.NumberInput(attrs={'step': 'any'}),
            'texte_libre': forms.Textarea(attrs={'rows': 6}),
        }
        error_messages = {
            champ: {'required': "Placez le point : cherchez l'adresse ou cliquez sur la carte."}
            for champ in ('latitude', 'longitude')
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['syndicat'].queryset = SectionPage.objects.order_by('title')
        self.fields['latitude'].help_text = (
            "Remplies par la recherche d'adresse ou en cliquant sur la carte.")

    def clean(self):
        donnees = super().clean()
        lat, lng = donnees.get('latitude'), donnees.get('longitude')
        if lat is not None and not -90 <= lat <= 90:
            self.add_error('latitude', "Latitude hors limites (entre -90 et 90).")
        if lng is not None and not -180 <= lng <= 180:
            self.add_error('longitude', "Longitude hors limites (entre -180 et 180).")
        return donnees


def _suggestions():
    lignes = Implantation.objects.values_list('type_implantation', 'entreprise')
    types = libelles([t for t, _ in lignes])
    for t in TYPES_SUGGERES:
        types.setdefault(cle(t), t)
    return {
        'types_connus': sorted(types.values(), key=cle),
        'entreprises_connues': sorted(libelles([e for _, e in lignes]).values(), key=cle),
    }


class CarteView(AccesCarteMixin, View):

    def get(self, request):
        implantations = list(Implantation.objects.select_related('syndicat'))
        syndicats = sorted({i.syndicat for i in implantations}, key=lambda s: cle(s.title))
        couleur = {s.pk: COULEURS[n % len(COULEURS)] for n, s in enumerate(syndicats)}
        types = libelles(i.type_implantation for i in implantations)
        entreprises = libelles(i.entreprise for i in implantations)

        def compte(attribut, valeur):
            return sum(1 for i in implantations if cle(getattr(i, attribut)) == valeur)

        points = [{
            'id': i.pk,
            'nom': i.nom,
            'syndicat': i.syndicat.pk,
            'syndicat_nom': i.syndicat.title,
            'couleur': couleur[i.syndicat.pk],
            'type': cle(i.type_implantation),
            'type_nom': types.get(cle(i.type_implantation), ''),
            'entreprise': cle(i.entreprise),
            'entreprise_nom': entreprises.get(cle(i.entreprise), ''),
            'adresse': i.adresse,
            'lat': i.latitude,
            'lng': i.longitude,
            'contact': i.contact_nom,
            'telephone': i.telephone,
            'email': i.email,
            'notes': i.texte_libre,
            'modifier': f'/cms/implantations/{i.pk}/',
        } for i in implantations]

        return render(request, 'cms/implantations/carte.html', {
            'points': points,
            'syndicats': [{
                'pk': s.pk, 'nom': s.title, 'couleur': couleur[s.pk],
                'nombre': sum(1 for i in implantations if i.syndicat_id == s.pk),
            } for s in syndicats],
            'types': [{'cle': k, 'nom': v, 'nombre': compte('type_implantation', k)}
                      for k, v in sorted(types.items(), key=lambda kv: kv[0])],
            'sans_type': compte('type_implantation', ''),
            'entreprises': [{'cle': k, 'nom': v, 'nombre': compte('entreprise', k)}
                            for k, v in sorted(entreprises.items(), key=lambda kv: kv[0])],
        })


class ImplantationEditView(AccesCarteMixin, View):
    """Ajout (pk absent) ou modification d'une implantation."""

    def _objet(self, pk):
        return get_object_or_404(Implantation, pk=pk) if pk else None

    def _rendu(self, request, form, objet):
        return render(request, 'cms/implantations/formulaire.html', {
            'form': form, 'objet': objet, **_suggestions(),
        })

    def get(self, request, pk=None):
        objet = self._objet(pk)
        return self._rendu(request, ImplantationForm(instance=objet), objet)

    def post(self, request, pk=None):
        objet = self._objet(pk)
        form = ImplantationForm(request.POST, instance=objet)
        if not form.is_valid():
            return self._rendu(request, form, objet)
        implantation = form.save(commit=False)
        implantation.modifie_par = request.user
        implantation.save()
        messages.success(request, f"Implantation « {implantation.nom} » enregistrée.")
        return redirect('cms_implantations')


class ImplantationSupprimerView(AccesCarteMixin, View):

    def get(self, request, pk):
        objet = get_object_or_404(Implantation, pk=pk)
        return render(request, 'cms/implantations/supprimer.html', {'objet': objet})

    def post(self, request, pk):
        objet = get_object_or_404(Implantation, pk=pk)
        nom = objet.nom
        objet.delete()
        messages.success(request, f"Implantation « {nom} » supprimée.")
        return redirect('cms_implantations')
