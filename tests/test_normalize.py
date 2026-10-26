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
    assert normalisera_organ_typ("Teknik- och fastighetsnämnden") == "namnd"
    assert normalisera_organ_typ("Hamn- och gatunämnden") == "namnd"
    assert normalisera_organ_typ("Energi-, miljö- och naturnämnden") == "namnd"
    assert normalisera_organ_typ("Miljö- och energirådet") == "rad"
    assert normalisera_organ_typ("Kommunkoncernen") == "ovrigt"
    assert normalisera_organ_typ("Styrelsen Vårgårda Bostäder AB") == "bolag"
    assert normalisera_organ_typ("Nordanstig Vatten AB revisor") == "revision"


def test_epost():
    assert hitta_epost("mailto:Anna.Berg@Politik.Solna.se") == "anna.berg@politik.solna.se"
    assert hitta_epost("ingen adress") == ""


def test_provkorning_2026_10_25():
    from plenum.normalize import skala_rollprefix, ar_personnamn
    from plenum.adapters.generic_table import rensa_organnamn, period_ur
    assert normalisera_parti("Moderaterna (M") == "M"
    assert skala_rollprefix("Ordförande: Cecilia Holm") == ("Cecilia Holm", "Ordförande")
    assert normalisera_roll(skala_rollprefix("2:a vice ordf. Agneta Nilsson")[1]) == "andre_vice_ordforande"
    assert not ar_personnamn("Samverkan mellan")
    assert not ar_personnamn("Moderata samlingspartiet")
    assert ar_personnamn("Gun Alexandersson-Malm")
    assert rensa_organnamn("Ledamöter och ersättare i kommunfullmäktige 2022 (oktober)-2026") == "Kommunfullmäktige"
    assert period_ur("Kommunstyrelsen 2023-2026") == "2023-2026"
    assert rensa_organnamn("Politiker i Kommunfullmäktige") == "Kommunfullmäktige"
