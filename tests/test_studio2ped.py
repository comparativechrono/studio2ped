"""Tests for studio2ped.

The drawings in tests/data are fictional families: four from the Hearn lab's
pedigree practical, and one (features) with every kind of symbol and line
Pedigree Studio draws. tests/data/expected holds what studio2ped 0.2.0 writes
for each of them.
"""
import contextlib
import copy
import io
import json
import os

import pytest

import studio2ped
from studio2ped.cli import main
from studio2ped.converter import default_output_prefix, split_condition_name

DATA = os.path.join(os.path.dirname(__file__), "data")
EXAMPLES = ["okafor", "price", "lynch", "cf-cousins", "features"]


def load(name):
    with open(os.path.join(DATA, name + ".studio.json"), encoding="utf-8") as fh:
        return json.load(fh)


def rows(text):
    """The data lines of a PED or MPED file, as lists of columns."""
    return [line.split("\t") for line in text.splitlines() if line and not line.startswith("#")]


def person(pid, shape="male", x=0, y=0, **extra):
    return dict({"id": pid, "shape": shape, "x": x, "y": y}, **extra)


def test_every_example_gives_a_valid_pedigree():
    for name in EXAMPLES:
        result = studio2ped.convert(load(name), name)
        assert len(result.files) == 1, name
        table = rows(result.files[0][1])
        ids = [r[1] for r in table]
        assert len(ids) == len(set(ids)), name                  # no one shares an identifier
        for r in table:
            assert r[2] in ids or r[2] == "0", (name, r)        # parents are in the file
            assert r[3] in ids or r[3] == "0", (name, r)


def test_the_output_is_as_expected():
    for name in EXAMPLES:
        result = studio2ped.convert(load(name), name)
        filename, text = result.files[0]
        with open(os.path.join(DATA, "expected", filename), encoding="utf-8") as fh:
            assert text == fh.read(), name


def test_people_are_given_their_pedigree_numbers():
    result = studio2ped.convert(load("lynch"))
    ids = [r[1] for r in rows(result.files[0][1])]
    assert ids[:4] == ["I-1", "I-2", "II-1", "II-2"]
    # 0.1.0 named people from the text under their symbols (Alice_50, Bowel_cancer) and gave two cousins
    # labelled 26 the same id; none of that text is written now
    assert not {"Alice_50", "Bowel_cancer", "26"} & set(ids)
    assert "Alice" not in result.files[0][1]


def test_numbers_follow_pedigree_studio():
    """A new generation starts 80 px or more below the first symbol of the one above; each generation is
    numbered from the left, counting the "no children" and "infertile" symbols, as Pedigree Studio does."""
    session = {"persons": [
        person("a", x=300, y=100), person("b", "female", x=100, y=150),     # 50 px lower: still generation I
        person("c", x=200, y=179),                                         # 79 px below a: still I
        person("d", "female", x=50, y=180),                                # 80 px below a: generation II
        person("m", "no-offspring", x=10, y=200), person("e", x=400, y=210),
    ], "partnerships": [], "childLinks": []}
    numbers = studio2ped.pedigree_numbers(studio2ped.parse_session(session)[0])
    assert numbers == {"b": "I-1", "c": "I-2", "a": "I-3", "m": "II-1", "d": "II-2", "e": "II-3"}
    deep = {"persons": [person("p{}".format(i), y=i * 100) for i in range(14)], "partnerships": [], "childLinks": []}
    numbers = studio2ped.pedigree_numbers(studio2ped.parse_session(deep)[0])
    assert numbers["p11"] == "XII-1" and numbers["p12"] == "13-1"


def test_no_children_and_infertile_symbols_are_left_out():
    result = studio2ped.convert(load("features"))
    table = rows(result.files[0][1])
    assert len(table) == 27                                       # 29 symbols, two of them markers
    assert "FAM1 (27 individuals)" in result.summary
    assert any("no children" in n for n in result.notes)
    assert any("infertility" in n for n in result.notes)
    parents = {r[2] for r in table} | {r[3] for r in table}
    # the couples with a marker are still in the file, now without a child
    for note in result.notes:
        if "no children" in note or "infertility" in note:
            a, b = note.split(":")[0].split(" and ")
            assert a in {r[1] for r in table} and b in {r[1] for r in table}
            assert a not in parents and b not in parents


def test_ids_text_gives_version_0_1_0s_identifiers():
    result = studio2ped.convert(load("lynch"), ids="text")
    ids = {r[1] for r in rows(result.files[0][1])}
    assert {"Alice_50", "Bowel_cancer", "d_50", "p-gm"} <= ids
    # the two people labelled 26 can't both be 26, so each is given their pedigree number, with a note
    assert "26" not in ids and {"IV-1", "IV-3"} <= ids
    assert any("'26'" in n and "IV-1 and IV-3" in n for n in result.notes)


def test_ids_studio_and_drawing():
    session = load("okafor")
    studio_ids = studio2ped.convert(session, ids="studio").ids
    assert studio_ids == {p["id"]: p["id"] for p in session["persons"]}
    # a drawing numbered with numbers shows the pedigree numbers
    assert studio2ped.convert(session, ids="drawing").ids == studio2ped.convert(session).ids
    letters = dict(copy.deepcopy(session), numberingMode="letters")
    assert set(studio2ped.convert(letters, ids="drawing").ids.values()) >= {"I-A", "I-B", "II-A"}
    only = dict(copy.deepcopy(session), numberingMode="lettersonly")
    assert set(studio2ped.convert(only, ids="drawing").ids.values()) >= {"A", "B", "C"}


def test_free_text_labels_and_labels_that_cannot_be_used():
    session = {"numberingMode": "freetext", "persons": [
        person("f", x=0, y=0, customLabel="Grandad"), person("m", "female", x=100, y=0, customLabel="Lbl"),
        person("c1", x=0, y=150, customLabel="0"), person("c2", "female", x=100, y=150, customLabel="Kid"),
        person("c3", x=200, y=150, customLabel="Kid"), person("c4", x=300, y=150, customLabel="?!"),
    ], "partnerships": [{"id": "pr", "fromId": "f", "toId": "m"}],
        "childLinks": [{"id": "l{}".format(i), "partnershipId": "pr", "childId": c}
                       for i, c in enumerate(["c1", "c2", "c3", "c4"])]}
    result = studio2ped.convert(session, ids="drawing")
    assert result.ids == {"f": "Grandad", "m": "I-2", "c1": "II-1", "c2": "II-2", "c3": "II-3", "c4": "II-4"}
    assert any("labelled 0" in n for n in result.notes)
    assert any("'Kid'" in n for n in result.notes)
    assert any("II-4's label" in n for n in result.notes)
    table = rows(result.files[0][1])
    assert ["FAM1", "II-2", "Grandad", "I-2", "2", "1"] in table


def test_ontology_ids_are_taken_off_column_names():
    assert split_condition_name("Condition X [MONDO:0009061]") == ("Condition X", "MONDO:0009061")
    assert split_condition_name("Deafness (HP:0000365)") == ("Deafness", "HP:0000365")
    assert split_condition_name("Sickle cell anaemia (HbSS)") == ("Sickle cell anaemia (HbSS)", None)
    assert split_condition_name("[OMIM:219700]") == ("OMIM:219700", "OMIM:219700")
    assert split_condition_name("Asthma [hpo:0002099]") == ("Asthma", "HP:0002099")
    # only an ontology's id counts: a blood pressure in brackets is part of the name
    assert split_condition_name("Hypertension (BP:160/95)") == ("Hypertension (BP:160/95)", None)
    bp = load("price")
    bp["legendLabels"] = {"#c0392b": "Hypertension (BP:160/95)", "#8e44ad": "Breast cancer [MONDO:0007254]",
                          "#f1c40f": "Prostate cancer"}
    bp_result = studio2ped.convert(bp)
    assert bp_result.files[0][1].splitlines()[0].split("\t")[1:] == ["Hypertension_BP16095", "Breast_cancer",
                                                                     "Prostate_cancer"]
    assert not any("BP:160/95" in n for n in bp_result.notes)
    result = studio2ped.convert(load("features"))
    header = result.files[0][1].splitlines()[0].split("\t")
    assert header[1:] == ["Condition_X", "Condition_Y", "Condition_Z", "Carrier"]
    assert any("Condition_X" in n and "MONDO:0009061" in n for n in result.notes)
    # two conditions that would make the same column are told apart
    session = load("price")
    session["legendLabels"] = {"#c0392b": "Breast cancer", "#8e44ad": "Breast cancer [MONDO:0007254]",
                               "#f1c40f": "Prostate cancer"}
    header = studio2ped.convert(session).files[0][1].splitlines()[0].split("\t")
    assert header[1:] == ["Breast_cancer", "Breast_cancer_2", "Prostate_cancer"]


def test_the_ontologies_are_the_ones_studio2ga4gh_accepts():
    """studio2ped does not need pedigree-ga4gh, so it keeps its own copy of the ontologies whose ids come off a
    column name; when pedigree-ga4gh is installed, the copy must match the ontologies it can declare."""
    ontology = pytest.importorskip("pedigree_ga4gh.ontology")
    from studio2ped import converter
    assert set(converter.ONTOLOGY_PREFIXES) == set(ontology.RESOURCES)
    for alias, prefix in converter._PREFIX_NAMES.items():
        assert ontology.tidy_curie(alias + ":1") == prefix + ":1"


def test_adoptive_and_surrogate_parents_are_not_genetic_parents():
    """A dashed line (an adoption) and a parent marked S (a gestational carrier) give no genetic parent, as in
    studio2ga4gh's PED-style pedigree; the people stay in the family, in the generation the drawing shows."""
    features = studio2ped.convert(load("features"))
    table = {r[1]: r for r in rows(features.files[0][1])}
    assert table["III-1"][2:4] == ["II-2", "0"]        # II-3, the mother in the drawing, is a surrogate
    assert table["III-3"][2:4] == ["0", "0"]           # adopted by II-6 and II-7
    assert table["III-2"][2:4] == ["II-5", "II-4"]     # a donor (D) is a genetic parent
    assert any("II-3 carried III-1 as a surrogate" in n for n in features.notes)
    assert any("II-6 and II-7 adopted III-3" in n for n in features.notes)
    ids = [r[1] for r in rows(features.files[0][1])]
    assert ids.index("III-3") > ids.index("II-7")       # still listed with their generation
    price = studio2ped.convert(load("price"))
    assert {r[1]: r for r in rows(price.files[0][1])}["III-5"][2:4] == ["0", "0"]


def test_labels_become_identifiers_as_in_studio2ga4gh():
    """Spaces become underscores and other punctuation is dropped, the same rule studio2ga4gh uses, so a person
    has the same identifier in the PED file and the GA4GH files."""
    from studio2ped.converter import _sanitise_id
    assert _sanitise_id("J. Mensah") == "J_Mensah"
    assert _sanitise_id("  Ama  Owusu (b. 1950) ") == "Ama_Owusu_b_1950"
    assert _sanitise_id("II-3") == "II-3"


def test_output_names():
    assert default_output_prefix("okafor.studio.json") == "okafor"
    assert default_output_prefix(os.path.join("families", "Okafor.Studio.JSON")) == "Okafor"
    assert default_output_prefix("session.json") == "session"
    assert default_output_prefix("session") == "session"


def test_unknown_ids_choice_is_refused():
    with pytest.raises(ValueError):
        studio2ped.convert(load("okafor"), ids="names")


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def test_command_line(tmp_path):
    src = tmp_path / "okafor.studio.json"
    src.write_text(json.dumps(load("okafor")), encoding="utf-8")
    code, out, err = run_cli(str(src))
    assert code == 0, err
    assert (tmp_path / "okafor.mped").exists()                      # not okafor.studio.mped
    assert "Note: III-5 stands for 3 people" in out
    # version 0.1.0's options; the output folder is made if need be
    out_dir = tmp_path / "out"
    code, out, err = run_cli(str(src), "-o", "family", "-d", str(out_dir))
    assert code == 0 and (out_dir / "family.mped").exists()
    code, out, err = run_cli(str(src), "-o", "named", "-d", str(out_dir), "--ids", "text")
    assert code == 0 and "Written" in out
    code, out, err = run_cli(str(tmp_path / "missing.json"))
    assert code == 1 and "not found" in err
    with pytest.raises(SystemExit):
        run_cli(str(src), "--ids", "names")
