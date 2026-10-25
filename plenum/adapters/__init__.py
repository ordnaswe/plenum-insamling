from .troman import TromanAdapter
from .generic_table import GenericTableAdapter
from .manual import ManualAdapter
from .netpublicator import NetpublicatorAdapter

ADAPTRAR = {
    "troman": TromanAdapter,
    "generic_table": GenericTableAdapter,
    "manual": ManualAdapter,
    "netpublicator": NetpublicatorAdapter,
    # "system2": lägg till här när vi vet vilket det andra stora systemet är
}


def skapa(kalla, hamtare):
    try:
        return ADAPTRAR[kalla.adapter](kalla, hamtare)
    except KeyError:
        raise ValueError(f"Okänd adapter '{kalla.adapter}' för {kalla.org_slug}")
