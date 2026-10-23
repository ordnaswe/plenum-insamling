from scrapling.parser import Selector
from plenum.adapters.tabell import tolka_tabeller, tolka_listor
from plenum.normalize import berika

HTML = """<html><body><h1>Socialnämnden</h1>
<table><tr><th>Namn</th><th>Parti</th><th>Uppdrag</th><th>E-post</th></tr>
<tr><td>Anna Berg</td><td>S</td><td>Ordförande</td><td><a href="mailto:anna.berg@kommun.se">e-post</a></td></tr>
<tr><td>Bo Lind</td><td>M</td><td>1:e vice ordförande</td><td></td></tr></table>
<ul><li>Cia Ek (SD), ersättare</li><li>Kontakta oss (öppettider)</li></ul>
</body></html>"""


def test_tabell_och_lista():
    p = Selector(HTML, url="https://x.se/sn")
    t = list(tolka_tabeller(p, "x", "Socialnämnden", "https://x.se/sn"))
    assert [o.namn_raw for o in t] == ["Anna Berg", "Bo Lind"]
    assert t[0].epost == "anna.berg@kommun.se"
    for o in t: berika(o)
    assert t[1].roll == "forste_vice_ordforande" and t[0].parti == "S"
    l = list(tolka_listor(p, "x", "Socialnämnden", "https://x.se/sn"))
    assert len(l) == 1 and l[0].parti_raw == "SD" and l[0].roll_raw == "ersättare"
