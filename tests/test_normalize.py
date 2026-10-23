from plenum.normalize import normalisera_roll, normalisera_parti, dela_namn, normalisera_organ_typ, hitta_epost


def test_roller():
    assert normalisera_roll("Ordförande") == "ordforande"
    assert normalisera_roll("Förste vice ordförande") == "forste_vice_ordforande"
    assert normalisera_roll("1:e v ordf") == "forste_vice_ordforande"
    assert normalisera_roll("2:e vice ordförande") == "andre_vice_ordforande"
    assert normalisera_roll("Andre vice ordförande") == "andre_vice_ordforande"
    assert normalisera_roll("Vice ordförande") == "vice_ordforande"
    assert normalisera_roll("Ledamot") == "ledamot"
    assert normalisera_roll("ersättare") == "ersattare"
    assert normalisera_roll("Ersättare revisor") == "ersattare_revisor"
    assert normalisera_roll("Lekmannarevisor") == "lekmannarevisor"
    assert normalisera_roll("Ersättare för ombud") == "ersattare_ombud"
    assert normalisera_roll("GDPR, GDPR, GDPR") == "ovrigt"


def test_partier():
    assert normalisera_parti("Socialdemokraterna") == "S"
    assert normalisera_parti("(M)") == "M"
    assert normalisera_parti("kd") == "KD"
    assert normalisera_parti("Sjukvårdspartiet i Värmland") == "Sjukvårdspartiet i Värmland"
    assert normalisera_parti("-") == ""


def test_namn():
    assert dela_namn("Anna Berg") == ("Anna", "Berg", False, "")
    assert dela_namn("ADAM PALM") == ("Adam", "Palm", False, "")
    assert dela_namn("(Ox) Dag Bergentoft") == ("Dag", "Bergentoft", False, "")
    assert dela_namn("Carl von Essen") == ("Carl", "von Essen", False, "")
    assert dela_namn("Anna Berg (S)")[3] == "S"
    assert dela_namn("Adam Algotsson Johnstone")[2] is True  # flaggas osäkert
    assert dela_namn("-") == ("", "", True, "")


def test_organ():
    assert normalisera_organ_typ("Kommunfullmäktige") == "fullmaktige"
    assert normalisera_organ_typ("Kommunstyrelsen") == "styrelse"
    assert normalisera_organ_typ("Kommunstyrelsens personalutskott") == "utskott"
    assert normalisera_organ_typ("Nyköpings-Oxelösunds Överförmyndarnämnd") == "namnd"
    assert normalisera_organ_typ("Haninge Bostäder AB") == "bolag"


def test_epost():
    assert hitta_epost("mailto:Anna.Berg@Politik.Solna.se") == "anna.berg@politik.solna.se"
    assert hitta_epost("ingen adress") == ""
