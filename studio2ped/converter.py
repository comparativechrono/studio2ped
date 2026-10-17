"""
studio2ped - Convert Pedigree Studio session JSON to PED/MPED pedigree files.

Core converter module: parses Pedigree Studio session data, detects separate
pedigrees via graph traversal, extracts phenotypes from visual markers and
legend labels, and emits standard PED files (single phenotype) or extended
MPED files (multiple phenotypes).

People are identified by their pedigree numbers (II-3) unless another kind of
identifier is asked for: see :func:`individual_ids`.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

# ── PED phenotype codes ───────────────────────────────────────────────────
PHENO_UNKNOWN = 0
PHENO_UNAFFECTED = 1
PHENO_AFFECTED = 2
PHENO_CARRIER = 3  # MPED only

# ── Sex codes ─────────────────────────────────────────────────────────────
SHAPE_TO_SEX = {
    "male": 1, "female": 2, "unknown": 0,
    "adopted-male": 1, "adopted-female": 2, "adopted-unknown": 0,
    "miscarriage": 0, "no-offspring": 0, "infertile": 0,
}

# Symbols that are not people: the bar under a couple for "no children" and the
# double bar for infertility. Pedigree Studio stores them as children of the
# couple, so they have to be taken out before the family is written.
MARKERS = {"no-offspring": "no children", "infertile": "infertility"}

# The kinds of identifier --ids offers (see individual_ids)
ID_CHOICES = ("numbers", "drawing", "studio", "text")

_ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]


# ── Data models ───────────────────────────────────────────────────────────

@dataclass
class Person:
    """A person extracted from a Pedigree Studio session."""
    id: str
    shape: str
    sex: int
    text: str                        # annotation text (may contain name, dob, etc.)
    fill_mode: str                   # 'none'|'solid'|'half'|'quartered'|'shading'
    fill_color: Optional[str]        # hex colour for solid fill
    halves: list                     # [left_colour|None, right_colour|None]
    quarters: list                   # [TR, BR, BL, TL] colours or None
    shading_pattern: str             # 'stripes'|'dots'
    shading_coverage: str            # 'full'|'half-left'|'half-right'
    center_text: str                 # 'S'|'P'|'D'|'dot'|''
    deceased: bool
    custom_label: str
    father_id: Optional[str] = None  # the genetic parents, resolved during graph analysis
    mother_id: Optional[str] = None
    drawn_father_id: Optional[str] = None  # the parents the drawing joins them to, adoptive and
    drawn_mother_id: Optional[str] = None  # surrogate included: used for the generations
    family_id: Optional[str] = None
    generation: int = -1
    x: float = 0.0                   # position in the drawing
    y: float = 0.0
    position: int = 0                # order in the drawing: by row, then left to right

    @property
    def is_marker(self) -> bool:
        """True for the "no children" and "infertile" symbols, which are not people."""
        return self.shape in MARKERS


@dataclass
class Partnership:
    """A partnership connection."""
    id: str
    from_id: str
    to_id: str
    type: str  # 'normal'|'consanguineous'|'separated'


@dataclass
class ChildLink:
    """A parent-child connection."""
    id: str
    partnership_id: str
    child_id: str
    dashed: bool  # dashed = adoption


@dataclass
class Phenotype:
    """A phenotype derived from the legend/visual markers."""
    name: str           # legend label text, e.g. "Breast cancer"
    key: str            # legend key, e.g. "#c0392b" or "shading:stripes:full"
    is_shading: bool    # True if this is a shading pattern phenotype
    color: Optional[str]        # hex colour (for colour-based phenotypes)
    pattern: Optional[str]      # 'stripes'|'dots' (for shading phenotypes)
    coverage: Optional[str]     # 'full'|'half-left'|'half-right' (for shading)


@dataclass
class Family:
    """A connected pedigree (one connected component of the graph)."""
    family_id: str
    person_ids: set
    persons: dict           # id -> Person
    partnerships: list      # Partnership objects
    child_links: list       # ChildLink objects


# ── Session parser ────────────────────────────────────────────────────────

def _number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_session(data: dict) -> tuple[dict[str, Person], list[Partnership], list[ChildLink], dict]:
    """Parse a Pedigree Studio session JSON into internal data structures.

    Returns (persons, partnerships, child_links, legend_labels).
    """
    persons = {}
    for pd in data.get("persons", []):
        pid = pd["id"]
        persons[pid] = Person(
            id=pid,
            shape=pd.get("shape", "unknown"),
            sex=SHAPE_TO_SEX.get(pd.get("shape", "unknown"), 0),
            text=pd.get("text", ""),
            fill_mode=pd.get("fillMode", "none"),
            fill_color=pd.get("fillColor"),
            halves=pd.get("halves", [None, None]),
            quarters=pd.get("quarters", [None, None, None, None]),
            shading_pattern=pd.get("shadingPattern", "stripes"),
            shading_coverage=pd.get("shadingCoverage", "full"),
            center_text=pd.get("centerText", ""),
            deceased=pd.get("deceased", False),
            custom_label=pd.get("customLabel", ""),
            x=_number(pd.get("x")),
            y=_number(pd.get("y")),
        )

    partnerships = []
    for pd in data.get("partnerships", []):
        partnerships.append(Partnership(
            id=pd["id"],
            from_id=pd["fromId"],
            to_id=pd["toId"],
            type=pd.get("type", "normal"),
        ))

    child_links = []
    for cd in data.get("childLinks", []):
        child_links.append(ChildLink(
            id=cd["id"],
            partnership_id=cd["partnershipId"],
            child_id=cd["childId"],
            dashed=cd.get("dashed", False),
        ))

    legend_labels = data.get("legendLabels", {})

    return persons, partnerships, child_links, legend_labels


# ── Graph analysis ────────────────────────────────────────────────────────

def detect_families(
    persons: dict[str, Person],
    partnerships: list[Partnership],
    child_links: list[ChildLink],
) -> list[Family]:
    """Detect separate pedigrees (connected components) via BFS graph traversal.

    Uses partnership and child link connections — not spatial position.
    Returns a list of Family objects, each containing its persons, partnerships,
    and child links.
    """
    # Build adjacency: person_id -> set of connected person_ids
    adj: dict[str, set[str]] = defaultdict(set)

    # Partnership ID -> Partnership object
    pship_map: dict[str, Partnership] = {p.id: p for p in partnerships}

    # Build adjacency from partnerships
    for p in partnerships:
        if p.from_id in persons and p.to_id in persons:
            adj[p.from_id].add(p.to_id)
            adj[p.to_id].add(p.from_id)

    # Build adjacency from child links (child ↔ both parents)
    for cl in child_links:
        pship = pship_map.get(cl.partnership_id)
        if pship and cl.child_id in persons:
            if pship.from_id in persons:
                adj[cl.child_id].add(pship.from_id)
                adj[pship.from_id].add(cl.child_id)
            if pship.to_id in persons:
                adj[cl.child_id].add(pship.to_id)
                adj[pship.to_id].add(cl.child_id)

    # BFS connected components
    visited: set[str] = set()
    families: list[Family] = []
    fam_counter = 0

    for pid in persons:
        if pid in visited:
            continue
        # BFS from this person
        fam_counter += 1
        component: set[str] = set()
        queue = [pid]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            component.add(current)
            for neighbour in adj.get(current, set()):
                if neighbour not in visited:
                    queue.append(neighbour)

        # Collect partnerships and child links for this component
        fam_partnerships = [p for p in partnerships
                           if p.from_id in component or p.to_id in component]
        fam_child_links = [cl for cl in child_links
                          if cl.child_id in component]

        fam_persons = {pid: persons[pid] for pid in component}
        fam_id = f"FAM{fam_counter}"

        families.append(Family(
            family_id=fam_id,
            person_ids=component,
            persons=fam_persons,
            partnerships=fam_partnerships,
            child_links=fam_child_links,
        ))

    return families


def resolve_parents(family: Family) -> list:
    """For each person in the family, determine their parents from the child
    link and partnership graph.

    ``drawn_father_id`` and ``drawn_mother_id`` are the couple the drawing
    joins a person to. ``father_id`` and ``mother_id`` are their genetic
    parents, which the PED file gives: a dashed line (an adoption) gives no
    genetic parents, and a parent marked S, a gestational carrier (surrogate),
    is not a genetic parent, as in studio2ga4gh's PED-style pedigree.

    Returns what was not written as a parent, as ``("adopted", child, (a, b))``
    and ``("surrogate", child, carrier, "mother" or "father")``.
    """
    pship_map = {p.id: p for p in family.partnerships}
    left_out = []

    for cl in family.child_links:
        pship = pship_map.get(cl.partnership_id)
        if not pship:
            continue
        child = family.persons.get(cl.child_id)
        if not child:
            continue

        # Determine which partner is father and which is mother
        p1 = family.persons.get(pship.from_id)
        p2 = family.persons.get(pship.to_id)
        if not p1 or not p2:
            continue

        if p1.sex == 1 and p2.sex == 2:
            father, mother = p1, p2
        elif p1.sex == 2 and p2.sex == 1:
            father, mother = p2, p1
        else:
            # Same sex or unknown — use from_id as father, to_id as mother
            # (follows the convention used by Pedigree Studio)
            father, mother = p1, p2
        child.drawn_father_id, child.drawn_mother_id = father.id, mother.id

        if cl.dashed:
            # adoptive parents are not genetic parents; a solid line from the birth parents still counts
            left_out.append(("adopted", child.id, (p1.id, p2.id)))
            continue
        for parent, role in ((father, "father"), (mother, "mother")):
            if parent.center_text == "S":
                left_out.append(("surrogate", child.id, parent.id, role))
            elif role == "father":
                child.father_id = parent.id
            else:
                child.mother_id = parent.id

    # Set family_id on all persons
    for p in family.persons.values():
        p.family_id = family.family_id
    return left_out


def assign_generations(family: Family):
    """Assign generation numbers to all persons in the family via graph
    traversal. Founders (no parents in the family) get generation 0.
    Uses iterative propagation identical to ped2studio, along the lines of the
    drawing (so an adopted child is in the generation below their adoptive
    parents)."""
    persons = family.persons

    # Pass 1: founders
    for p in persons.values():
        has_father = p.drawn_father_id and p.drawn_father_id in persons
        has_mother = p.drawn_mother_id and p.drawn_mother_id in persons
        if not has_father and not has_mother:
            p.generation = 0

    # Pass 2: propagate
    changed = True
    while changed:
        changed = False
        for p in persons.values():
            if p.generation >= 0:
                continue
            f, m = p.drawn_father_id, p.drawn_mother_id
            fg = persons[f].generation if (f and f in persons) else -1
            mg = persons[m].generation if (m and m in persons) else -1
            if fg >= 0 and mg >= 0:
                p.generation = max(fg, mg) + 1
                changed = True
            elif fg >= 0 and not (m and m in persons):
                p.generation = fg + 1
                changed = True
            elif mg >= 0 and not (f and f in persons):
                p.generation = mg + 1
                changed = True

    # Pass 3: marry-in correction
    # Build partner lookup
    partner_of: dict[str, list[str]] = defaultdict(list)
    for pship in family.partnerships:
        if pship.from_id in persons and pship.to_id in persons:
            partner_of[pship.from_id].append(pship.to_id)
            partner_of[pship.to_id].append(pship.from_id)

    for p in persons.values():
        if p.generation >= 0:
            has_parent = (p.drawn_father_id and p.drawn_father_id in persons) or \
                         (p.drawn_mother_id and p.drawn_mother_id in persons)
            if has_parent:
                continue
            for pid in partner_of.get(p.id, []):
                partner = persons.get(pid)
                if partner and partner.generation > p.generation:
                    p.generation = partner.generation
                    break

    # Fallback
    for p in persons.values():
        if p.generation < 0:
            p.generation = 0


# ── Phenotype extraction ──────────────────────────────────────────────────

def extract_phenotypes(legend_labels: dict) -> list[Phenotype]:
    """Extract phenotype definitions from the legend labels.

    Legend keys can be:
    - Hex colour strings: '#c0392b' → colour-based phenotype
    - Shading key strings: 'shading:stripes:full' → shading-based phenotype

    Returns a list of Phenotype objects.
    """
    phenotypes = []
    for key, label in legend_labels.items():
        if not label or not label.strip():
            continue  # skip unlabelled entries

        label = label.strip()

        if key.startswith("shading:"):
            # Parse shading key: "shading:{pattern}:{coverage}"
            parts = key.split(":")
            pattern = parts[1] if len(parts) > 1 else "stripes"
            coverage = parts[2] if len(parts) > 2 else "full"
            phenotypes.append(Phenotype(
                name=label, key=key, is_shading=True,
                color=None, pattern=pattern, coverage=coverage,
            ))
        else:
            # Colour-based phenotype
            phenotypes.append(Phenotype(
                name=label, key=key, is_shading=False,
                color=key, pattern=None, coverage=None,
            ))

    return phenotypes


def classify_person_phenotypes(
    person: Person,
    phenotypes: list[Phenotype],
) -> dict[str, int]:
    """Determine which phenotypes a person expresses and whether they are
    affected or carrier for each.

    Returns a dict of phenotype_name -> status code:
      0 = unknown/not applicable
      1 = unaffected
      2 = affected
      3 = carrier

    Logic:
    - Solid fill matching a colour phenotype → affected (2)
    - Full shading matching a shading phenotype → affected (2)
    - Half fill with one half matching a colour phenotype → carrier (3)
    - Half shading matching a shading phenotype with half coverage → carrier (3)
    - Quartered fill with any quarter matching a colour phenotype → affected (2)
    - Centre dot ('dot') → add carrier status for all phenotypes that person has
    - No matching fill → unaffected (1)
    """
    results = {ph.name: PHENO_UNAFFECTED for ph in phenotypes}

    # Collect all colour markers on this person
    person_colours: set[str] = set()
    is_half_colour: dict[str, bool] = {}  # colour -> True if only in a half fill

    if person.fill_mode == "solid" and person.fill_color:
        person_colours.add(person.fill_color)
        is_half_colour[person.fill_color] = False

    elif person.fill_mode == "half":
        for i, c in enumerate(person.halves or []):
            if c:
                person_colours.add(c)
                # If only one half is filled, it's a carrier indication
                other = person.halves[1 - i] if person.halves else None
                if not other:
                    is_half_colour[c] = True
                else:
                    is_half_colour[c] = False

    elif person.fill_mode == "quartered":
        for c in (person.quarters or []):
            if c:
                person_colours.add(c)
                is_half_colour[c] = False  # quartered = affected

    # Match colour phenotypes
    for ph in phenotypes:
        if ph.is_shading:
            continue
        if ph.color and ph.color in person_colours:
            if is_half_colour.get(ph.color, False):
                results[ph.name] = PHENO_CARRIER
            else:
                results[ph.name] = PHENO_AFFECTED

    # Match shading phenotypes
    if person.fill_mode == "shading":
        person_shading_key = f"shading:{person.shading_pattern}:{person.shading_coverage}"
        for ph in phenotypes:
            if not ph.is_shading:
                continue
            if ph.key == person_shading_key:
                if person.shading_coverage in ("half-left", "half-right"):
                    results[ph.name] = PHENO_CARRIER
                else:
                    results[ph.name] = PHENO_AFFECTED
            # Also check if the pattern matches but coverage differs
            # (e.g. legend says "shading:stripes:full" but person has "shading:stripes:half-left")
            elif ph.pattern == person.shading_pattern:
                full_key = f"shading:{person.shading_pattern}:full"
                if ph.key == full_key and person.shading_coverage in ("half-left", "half-right"):
                    results[ph.name] = PHENO_CARRIER

    # Centre dot overrides: if person has a carrier dot and any phenotype
    # is marked affected, downgrade to carrier. If no phenotype is marked,
    # mark the first phenotype as carrier.
    if person.center_text == "dot":
        has_any = any(v >= PHENO_AFFECTED for v in results.values())
        if has_any:
            for name in results:
                if results[name] == PHENO_AFFECTED:
                    results[name] = PHENO_CARRIER
        elif phenotypes:
            results[phenotypes[0].name] = PHENO_CARRIER

    return results


def has_carrier_notation(persons: dict[str, Person]) -> bool:
    """Check if any person in the pedigree uses carrier notation
    (centre dot, or half fill/shading with one side empty)."""
    for p in persons.values():
        if p.center_text == "dot":
            return True
        if p.fill_mode == "half":
            filled = sum(1 for h in (p.halves or []) if h)
            if filled == 1:
                return True
        if p.fill_mode == "shading" and p.shading_coverage in ("half-left", "half-right"):
            return True
    return False


# ── ID generation ─────────────────────────────────────────────────────────

def drawn_rows(persons: dict[str, Person]) -> list[list[Person]]:
    """The rows (generations) of the drawing as Pedigree Studio numbers them.

    Everyone is sorted from top to bottom, the "no children" and "infertile"
    symbols included; a new row starts 80 px or more below the first symbol of
    the row above, and each row is read from left to right.
    """
    rows: list[list[Person]] = []
    for p in sorted(persons.values(), key=lambda q: q.y):
        if rows and p.y - rows[-1][0].y < 80:
            rows[-1].append(p)
        else:
            rows.append([p])
    return [sorted(row, key=lambda q: q.x) for row in rows]


def _generation_label(index: int) -> str:
    return _ROMAN[index] if index < len(_ROMAN) else str(index + 1)


def pedigree_numbers(persons: dict[str, Person]) -> dict[str, str]:
    """Pedigree numbers as Pedigree Studio shows them: the generation in Roman
    numerals and the position from the left, such as ``II-3``."""
    out = {}
    for gi, row in enumerate(drawn_rows(persons)):
        for pi, p in enumerate(row):
            out[p.id] = f"{_generation_label(gi)}-{pi + 1}"
    return out


def _letters(n: int) -> str:
    s = ""
    while n >= 0:
        s = chr(65 + n % 26) + s
        n = n // 26 - 1
    return s


def drawing_labels(persons: dict[str, Person], numbering_mode: str = "numbers") -> dict[str, str]:
    """The label each symbol shows in the drawing under its numbering setting:
    pedigree numbers (``numbers``, and ``off``), letters (``letters``: II-A;
    ``lettersonly``: A, B, C ...) or the labels typed in (``freetext``, where a
    symbol without one shows its pedigree number)."""
    numbers = pedigree_numbers(persons)
    if numbering_mode == "freetext":
        out = {}
        for pid, p in persons.items():
            label = (p.custom_label or "").strip()
            out[pid] = label if label and label != "Lbl" else numbers[pid]
        return out
    if numbering_mode in ("letters", "lettersonly"):
        out, k = {}, 0
        for gi, row in enumerate(drawn_rows(persons)):
            for pi, p in enumerate(row):
                out[p.id] = _letters(k) if numbering_mode == "lettersonly" else f"{_generation_label(gi)}-{_letters(pi)}"
                k += 1
        return out
    return numbers


def _sanitise_id(raw: str) -> str:
    """Spaces become underscores; anything but letters, digits, _ and - is dropped."""
    s = re.sub(r"\s+", "_", (raw or "").strip())
    return re.sub(r"[^\w\-]", "", s)


def individual_ids(
    persons: dict[str, Person],
    ids: str = "numbers",
    numbering_mode: str = "numbers",
) -> tuple[dict[str, str], list[str]]:
    """The identifier each person is given in the PED file, and notes about them.

    ``ids`` is one of :data:`ID_CHOICES`:

    * ``numbers`` (the default): pedigree numbers, such as ``II-3``;
    * ``drawing``: the labels the drawing shows under its numbering setting;
    * ``studio``: Pedigree Studio's own ids, such as ``p-3``;
    * ``text``: version 0.1.0's identifiers (see :func:`make_individual_id`),
      which are often names.

    ``persons`` should include the "no children" and "infertile" symbols,
    because Pedigree Studio counts them when it numbers a row. Identifiers must
    be unique, so anyone whose identifier would be shared with someone else, or
    would be empty or ``0`` (which PED reads as "no parent"), is given their
    pedigree number instead, and a note says so.
    """
    if ids not in ID_CHOICES:
        raise ValueError(f"ids must be one of {', '.join(ID_CHOICES)}, not {ids!r}")
    numbers = pedigree_numbers(persons)
    people = [pid for pid, p in persons.items() if not p.is_marker]
    if ids == "numbers":
        return {pid: numbers[pid] for pid in people}, []
    if ids == "drawing":
        labels = drawing_labels(persons, numbering_mode)
        wanted = {pid: _sanitise_id(labels[pid]) for pid in people}
    elif ids == "studio":
        wanted = {pid: _sanitise_id(pid) for pid in people}
    else:
        wanted = {pid: make_individual_id(persons[pid]) for pid in people}
    notes: list[str] = []
    out = {}
    for pid in people:
        if wanted[pid] == "0":
            out[pid] = numbers[pid]
            notes.append(f"{numbers[pid]} is labelled 0, which PED reads as 'no parent', so their pedigree "
                         f"number is used instead")
        elif not wanted[pid]:
            out[pid] = numbers[pid]
            notes.append(f"{numbers[pid]}'s label has nothing that can go into an identifier, so their pedigree "
                         f"number is used instead")
        else:
            out[pid] = wanted[pid]
    while True:
        counts = Counter(out.values())
        clashes = defaultdict(list)
        for pid in people:
            if counts[out[pid]] > 1 and out[pid] != numbers[pid]:
                clashes[out[pid]].append(pid)
        if not clashes:
            break
        for label, pids in clashes.items():
            for pid in pids:
                out[pid] = numbers[pid]
            notes.append("'{}' would identify more than one person, so {} {} identified by their pedigree "
                         "number{} instead".format(label, _and(numbers[pid] for pid in pids),
                                                   "is" if len(pids) == 1 else "are", "" if len(pids) == 1 else "s"))
    return out, notes


def _and(items) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def make_individual_id(person: Person) -> str:
    """Version 0.1.0's identifier for a person (``--ids text``).

    Priority: custom label → annotation text first line → person ID.
    Sanitises to remove whitespace and special characters.
    """
    # Try custom label
    if person.custom_label and person.custom_label.strip() and person.custom_label.strip() != "Lbl":
        raw = person.custom_label.strip()
    # Try first line of annotation text
    elif person.text and person.text.strip():
        raw = person.text.strip().split("\n")[0].strip()
    else:
        raw = person.id

    # Sanitise: replace whitespace with underscore, remove non-alphanumeric except _-
    sanitised = re.sub(r"\s+", "_", raw)
    sanitised = re.sub(r"[^\w\-]", "", sanitised)
    if not sanitised:
        sanitised = person.id
    return sanitised


# ── PED/MPED output ──────────────────────────────────────────────────────

def _rows_in_order(family: Family) -> list[Person]:
    """Everyone in the family, generation by generation, each generation in the
    order of the drawing (Pedigree Studio's id breaks any tie)."""
    return sorted(family.persons.values(), key=lambda p: (p.generation, p.position, p.id))


def build_standard_ped(family: Family, phenotypes: list[Phenotype], ids: Optional[dict] = None) -> str:
    """Build a standard 6-column PED file for a single-phenotype family.

    If there's exactly one phenotype, affected=2, carrier/unaffected=1.
    If there are no phenotypes, all get phenotype 1 (unaffected).
    ``ids`` maps Pedigree Studio's ids to the identifiers to write (see
    :func:`individual_ids`); without it, version 0.1.0's identifiers are used.
    """
    lines = [f"# Family: {family.family_id}"]
    lines.append("# FamID\tIndID\tFatherID\tMotherID\tSex\tPhenotype")

    sorted_persons = _rows_in_order(family)

    id_map = ids if ids is not None else {p.id: make_individual_id(p) for p in sorted_persons}

    for p in sorted_persons:
        ind_id = id_map[p.id]
        father = id_map.get(p.father_id, "0") if p.father_id else "0"
        mother = id_map.get(p.mother_id, "0") if p.mother_id else "0"

        # Determine phenotype
        if phenotypes:
            statuses = classify_person_phenotypes(p, phenotypes)
            # For standard PED: affected if any phenotype is AFFECTED
            max_status = max(statuses.values()) if statuses else PHENO_UNAFFECTED
            if max_status == PHENO_AFFECTED:
                pheno = PHENO_AFFECTED
            else:
                pheno = PHENO_UNAFFECTED
        else:
            pheno = PHENO_UNAFFECTED

        lines.append(f"{family.family_id}\t{ind_id}\t{father}\t{mother}\t{p.sex}\t{pheno}")

    return "\n".join(lines) + "\n"


def build_mped(family: Family, phenotypes: list[Phenotype], include_carrier: bool,
               ids: Optional[dict] = None) -> str:
    """Build an MPED (multi-phenotype PED) file.

    Format:
    - Header line: # MPED v1 <tab-separated phenotype names>
    - Column header: # FamID  IndID  FatherID  MotherID  Sex  <phenotype1>  <phenotype2>  ...
    - Data lines: standard PED columns + one column per phenotype

    Phenotype codes: 0=unknown, 1=unaffected, 2=affected, 3=carrier

    ``ids`` is as for :func:`build_standard_ped`.
    """
    # Build phenotype column names (sanitise for header)
    col_names = column_names(phenotypes)

    # Add a Carrier column if carrier notation is present and not already a phenotype
    carrier_col = None
    if include_carrier and not any(n.lower() == "carrier" for n in col_names):
        carrier_col = "Carrier"
        col_names.append(carrier_col)

    lines = [f"# MPED v1\t" + "\t".join(col_names)]
    lines.append("# FamID\tIndID\tFatherID\tMotherID\tSex\t" + "\t".join(col_names))

    sorted_persons = _rows_in_order(family)

    id_map = ids if ids is not None else {p.id: make_individual_id(p) for p in sorted_persons}

    for p in sorted_persons:
        ind_id = id_map[p.id]
        father = id_map.get(p.father_id, "0") if p.father_id else "0"
        mother = id_map.get(p.mother_id, "0") if p.mother_id else "0"

        statuses = classify_person_phenotypes(p, phenotypes)
        pheno_values = [str(statuses.get(ph.name, PHENO_UNAFFECTED)) for ph in phenotypes]

        # Carrier column (from centre dot, independent of other phenotypes)
        if carrier_col:
            if p.center_text == "dot":
                pheno_values.append(str(PHENO_CARRIER))
            else:
                pheno_values.append(str(PHENO_UNAFFECTED))

        line = f"{family.family_id}\t{ind_id}\t{father}\t{mother}\t{p.sex}"
        line += "\t" + "\t".join(pheno_values)
        lines.append(line)

    return "\n".join(lines) + "\n"


# An ontology id after a condition's name, as studio2ga4gh reads it from the
# colour key: "Breast cancer [MONDO:0007254]" or "Deafness (HP:0000365)"
_TRAILING_CURIE = re.compile(r"^(.*?)\s*[\[(]\s*([A-Za-z][A-Za-z0-9.\-]*):([^\s:_\])]+)\s*[\])]\s*$")

# The ontologies whose ids count as one in brackets: those pedigree-ga4gh, and so
# studio2ga4gh, can declare in a Phenopacket. Anything else in brackets, such as a
# blood pressure "(BP:160/95)", is part of the condition's name.
ONTOLOGY_PREFIXES = ("HP", "MONDO", "OMIM", "ORPHA", "DOID", "SNOMEDCT", "ICD10CM", "NCIT", "EFO", "GENO",
                     "HGNC", "UBERON", "SO", "ECO", "PATO", "UO", "CL", "NCBITaxon", "UCUM", "LOINC", "CHEBI",
                     "HANCESTRO", "MAXO", "DrugCentral")
_PREFIX_NAMES = {p.lower(): p for p in ONTOLOGY_PREFIXES}
_PREFIX_NAMES.update({"hpo": "HP", "mim": "OMIM", "orphanet": "ORPHA", "snomed": "SNOMEDCT", "sctid": "SNOMEDCT"})


def split_condition_name(name: str) -> tuple[str, Optional[str]]:
    """``"Breast cancer [MONDO:0007254]"`` -> ``("Breast cancer", "MONDO:0007254")``;
    a name without an ontology id in brackets comes back with ``None``, and so
    does one whose bracket holds something else (``"Hypertension (BP:160/95)"``)."""
    m = _TRAILING_CURIE.match(name or "")
    if m and m.group(2).lower() in _PREFIX_NAMES:
        curie = "{}:{}".format(_PREFIX_NAMES[m.group(2).lower()], m.group(3))
        return (m.group(1).strip() or curie), curie
    return (name or "").strip(), None


def _sanitise_column_name(name: str) -> str:
    """Sanitise a phenotype name for use as a column header (an ontology id in
    brackets after the name is left out)."""
    s = re.sub(r"\s+", "_", split_condition_name(name)[0])
    s = re.sub(r"[^\w\-]", "", s)
    return s or "Phenotype"


def column_names(phenotypes: list[Phenotype]) -> list[str]:
    """The MPED column for each phenotype; a name that would repeat gets _2, _3 ..."""
    out: list[str] = []
    for ph in phenotypes:
        base = _sanitise_column_name(ph.name)
        name, n = base, 1
        while name.lower() in (o.lower() for o in out):
            n += 1
            name = f"{base}_{n}"
        out.append(name)
    return out


# ── Public API ────────────────────────────────────────────────────────────

@dataclass
class ConversionResult:
    """Result of a conversion, containing one or more output files."""
    files: list  # list of (filename, content) tuples
    families: list[Family]
    phenotypes: list[Phenotype]
    is_multi_phenotype: bool
    summary: str
    notes: list = field(default_factory=list)  # symbols left out, identifiers changed and the like
    ids: dict = field(default_factory=dict)    # Pedigree Studio's id -> the identifier in the files


def convert(
    session_data: dict,
    output_prefix: str = "pedigree",
    *,
    ids: str = "numbers",
) -> ConversionResult:
    """Convert a Pedigree Studio session dict to PED/MPED file(s).

    Parameters
    ----------
    session_data : dict
        Parsed Pedigree Studio session JSON.
    output_prefix : str
        Base name for output files (without extension).
    ids : str
        How people are identified: ``"numbers"`` (pedigree numbers such as
        II-3, the default), ``"drawing"``, ``"studio"`` or ``"text"``; see
        :func:`individual_ids`.

    Returns
    -------
    ConversionResult
        Contains the generated file contents and metadata.
    """
    everyone, partnerships, child_links, legend_labels = parse_session(session_data)

    if not everyone:
        return ConversionResult(
            files=[], families=[], phenotypes=[],
            is_multi_phenotype=False, summary="No persons found in session.",
        )

    numbering_mode = session_data.get("numberingMode") or "numbers"
    id_map, notes = individual_ids(everyone, ids, numbering_mode)
    for i, p in enumerate(q for row in drawn_rows(everyone) for q in row):
        p.position = i

    # The "no children" and "infertile" symbols are not people: leave them out
    markers = {pid: p for pid, p in everyone.items() if p.is_marker}
    persons = {pid: p for pid, p in everyone.items() if not p.is_marker}
    pship_map = {pr.id: pr for pr in partnerships}
    noted = set()
    for cl in child_links:
        pr = pship_map.get(cl.partnership_id)
        if cl.child_id in markers and pr and pr.from_id in id_map and pr.to_id in id_map:
            a, b = sorted((everyone[pr.from_id], everyone[pr.to_id]), key=lambda q: q.position)
            notes.append(f"{id_map[a.id]} and {id_map[b.id]}: {MARKERS[markers[cl.child_id].shape]} "
                         f"(the symbol is not a person, so it is left out)")
            noted.add(cl.child_id)
    for pid, m in markers.items():
        if pid not in noted:
            notes.append(f"a '{MARKERS[m.shape]}' symbol that is not joined to a couple is left out")
    child_links = [cl for cl in child_links if cl.child_id not in markers]
    for pid, p in persons.items():
        if re.fullmatch(r"\d+|n", p.center_text or "", flags=re.I):
            notes.append(f"{id_map[pid]} stands for {p.center_text} people in the drawing but is written as one person")

    # Detect families (connected components)
    families = detect_families(persons, partnerships, child_links)

    # Resolve parent-child relationships and generations for each family
    for fam in families:
        for item in resolve_parents(fam):
            if item[0] == "adopted":
                _, child, (a, b) = item
                notes.append(f"{id_map[a]} and {id_map[b]} adopted {id_map[child]} (a dashed line): adoptive "
                             f"parents are not genetic parents, so they are not written as {id_map[child]}'s parents")
            else:
                _, child, carrier, role = item
                notes.append(f"{id_map[carrier]} carried {id_map[child]} as a surrogate (S): a gestational carrier is "
                             f"not a genetic parent, so {id_map[child]}'s {role} is written as 0")
        assign_generations(fam)

    # Extract phenotypes from legend
    phenotypes = extract_phenotypes(legend_labels)

    # Determine if multi-phenotype
    # Multi-phenotype if: more than one phenotype in the legend,
    # OR carrier notation is used alongside a phenotype
    carrier_present = any(has_carrier_notation(fam.persons) for fam in families)
    is_multi = len(phenotypes) > 1 or (len(phenotypes) == 1 and carrier_present)
    if is_multi:
        for ph, col in zip(phenotypes, column_names(phenotypes)):
            if split_condition_name(ph.name)[1]:
                notes.append(f"'{ph.name}' is the column {col} (a column name can't hold the ontology id)")

    # Build output files
    files: list[tuple[str, str]] = []

    for i, fam in enumerate(families):
        suffix = f"_{i + 1}" if len(families) > 1 else ""

        if is_multi:
            ext = ".mped"
            content = build_mped(fam, phenotypes, carrier_present, ids=id_map)
        else:
            ext = ".ped"
            content = build_standard_ped(fam, phenotypes, ids=id_map)

        filename = f"{output_prefix}{suffix}{ext}"
        files.append((filename, content))

    # Build summary
    fam_desc = ", ".join(
        f"{fam.family_id} ({len(fam.persons)} individuals)"
        for fam in families
    )
    pheno_desc = ", ".join(ph.name for ph in phenotypes) if phenotypes else "none"
    summary = (
        f"Detected {len(families)} pedigree(s): {fam_desc}. "
        f"Phenotypes: {pheno_desc}. "
        f"Format: {'MPED (multi-phenotype)' if is_multi else 'standard PED'}. "
        f"Carrier notation: {'yes' if carrier_present else 'no'}."
    )

    return ConversionResult(
        files=files,
        families=families,
        phenotypes=phenotypes,
        is_multi_phenotype=is_multi,
        summary=summary,
        notes=notes,
        ids=id_map,
    )


def default_output_prefix(input_path: str) -> str:
    """The input file's name without ``.studio.json``, or without its extension
    (``okafor.studio.json`` -> ``okafor``, ``session.json`` -> ``session``)."""
    base = os.path.basename(input_path)
    if base.lower().endswith(".studio.json"):
        return base[: -len(".studio.json")] or "pedigree"
    return os.path.splitext(base)[0]


def convert_file(
    input_path: str,
    output_prefix: Optional[str] = None,
    output_dir: Optional[str] = None,
    *,
    ids: str = "numbers",
) -> ConversionResult:
    """Read a Pedigree Studio session JSON and write PED/MPED files.

    Parameters
    ----------
    input_path : str
        Path to the input .json session file.
    output_prefix : str, optional
        Base name for output files. Defaults to the input file's name without
        ``.studio.json`` (or without its extension).
    output_dir : str, optional
        Directory for output files, made if it does not exist yet. Defaults to
        the input file's directory.
    ids : str
        How people are identified (see :func:`convert`).

    Returns
    -------
    ConversionResult
        Contains the written file paths and metadata.
    """
    with open(input_path, "r", encoding="utf-8-sig") as f:
        session_data = json.load(f)

    if output_prefix is None:
        output_prefix = default_output_prefix(input_path)

    if output_dir is None:
        output_dir = os.path.dirname(input_path) or "."

    result = convert(session_data, output_prefix, ids=ids)

    # Write files
    os.makedirs(output_dir, exist_ok=True)
    written_files = []
    for filename, content in result.files:
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        written_files.append((filepath, content))

    result.files = written_files
    return result
