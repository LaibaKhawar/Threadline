from app.extraction.entities import Gazetteer, extract_orgs, extract_people, extract_projects, org_from_domain


def gaz() -> Gazetteer:
    g = Gazetteer()
    g.add_person("Ahmed Khan", ["Ahmed"], ["ahmed@lumen.io"])
    g.add_person("Sarah Chen", ["Sarah"])
    g.orgs["acme corp"] = "Acme Corp"
    g.projects["atlas"] = "Atlas"
    return g


def test_gazetteer_people_full_and_first_names() -> None:
    names = [p.name for p in extract_people("Sarah said Ahmed Khan will review it.", gaz())]
    assert names == ["Sarah Chen", "Ahmed Khan"]


def test_unknown_names_need_context() -> None:
    names = [p.name for p in extract_people("Priya said the build is green. Monday works.", gaz())]
    assert "Priya" in names and "Monday" not in names


def test_greeting_addressee() -> None:
    ps = extract_people("Hi Laiba,\nthanks", gaz())
    assert ps[0].name == "Laiba" and ps[0].role == "addressee"


def test_orgs_and_projects() -> None:
    orgs = {o.name for o in extract_orgs("We met Acme Corp and Redline Security yesterday.", gaz())}
    assert {"Acme Corp", "Redline Security"} <= orgs
    projects = {p.name for p in extract_projects("Update on Project Phoenix and the atlas migration", gaz())}
    assert projects == {"Phoenix", "Atlas"}


def test_org_from_domain_ignores_freemail() -> None:
    assert org_from_domain("gmail.com") is None
    assert org_from_domain("helioshealth.com") == "Helioshealth"
