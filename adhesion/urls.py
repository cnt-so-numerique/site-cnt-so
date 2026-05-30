from django.urls import path

from . import views

app_name = 'adhesion'

urlpatterns = [
    path('adherer/<slug:site_slug>/', views.FormulaireView.as_view(), name='formulaire'),
    path('adherer/<slug:site_slug>/paiement/succes/', views.PaiementSuccesView.as_view(), name='paiement_succes'),
    path('adherer/<slug:site_slug>/paiement/annule/', views.PaiementAnnuleView.as_view(), name='paiement_annule'),
]
