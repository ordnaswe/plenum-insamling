"""Kommuner som inte publicerar något maskinläsbart. Adaptern gör inget men
registrerar körningen som 'ingen_kalla' så att det syns i statistiken och
Sandro kan begära ut listan via e-post i stället (offentlighetsprincipen)."""
from .base import Adapter


class ManualAdapter(Adapter):
    namn = "manual"

    def samla(self):
        return iter(())
