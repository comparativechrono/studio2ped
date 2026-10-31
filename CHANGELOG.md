# Changelog

## 0.2.1

- A parent marked G is a gestational carrier, and is not written as a genetic
  parent. Since the 2025 correction to the pedigree nomenclature (Steinhaus
  French, Bennett and Resta, *J Genet Couns* 2025;34(2):e2020), G marks a
  gestational carrier, and Pedigree Studio draws G where it used to draw S.
  S, which older drawings use, still means the same.
- The note says "gestational carrier" and gives the mark (G or S), not
  "surrogate": the corrected nomenclature keeps "surrogate" for a woman who
  gives the egg and carries the pregnancy, who is a genetic parent.
- A symbol divided into thirds, which Pedigree Studio now draws for three
  conditions, gives each of its colours as a condition the person has, as
  quarters do.

## 0.2.0

- People are now identified by their pedigree numbers (I-1, II-3 and so on),
  worked out exactly as Pedigree Studio shows them and as studio2ga4gh 0.4
  writes them, so the same person has the same identifier in the PED file and
  in the GA4GH files. Version 0.1.0 took identifiers from the text under each
  symbol, which usually holds a name and an age (`Alice_50`), sometimes a
  condition (`Bowel_cancer`), and is not always unique: in the Lynch example
  two cousins labelled 26 got the same identifier, which `mpedtools validate`
  rejects.
- `--ids` chooses the identifiers: `numbers` (the default), `drawing` (the
  labels the drawing shows under its numbering setting: numbers, letters or
  labels typed in), `studio` (Pedigree Studio's own ids) or `text` (0.1.0's
  identifiers). Whatever the choice, an identifier that would be shared by two
  people, be empty or be `0` (which PED reads as "no parent") is replaced by
  the person's pedigree number, and the command says so.
- The "no children" and "infertility" symbols are no longer written as
  people. Pedigree Studio stores them as children of the couple, so 0.1.0 put
  them in the file as individuals of unknown sex (29 individuals for the 27
  people in the features example). They are left out now, with a note naming
  the couple.
- Adoptive parents and surrogates are no longer written as parents. A child
  joined to a couple by a dashed line (an adoption) and a parent marked S (a
  gestational carrier) are not genetic relations, and a linkage program reads
  the father and mother columns as genetic parents, so 0.1.0's files gave
  wrong ones. Those parents are now 0, with a note, which is also what
  studio2ga4gh's PED-style pedigree gives: a solid line from birth parents
  still counts, and so does a donor (D).
- A symbol standing for several people (a number such as 3 in the symbol) is
  still written as one person, but the command now says so.
- An ontology id written after a condition's name in the colour key, as
  studio2ga4gh reads it (`Condition X [MONDO:0009061]`), is left out of the
  MPED column name, which is now `Condition_X` instead of
  `Condition_X_MONDO0009061`. Only the ids of ontologies count (the HPO,
  Mondo, OMIM, Orphanet, SNOMED CT and the others studio2ga4gh can declare):
  anything else in brackets, such as `Hypertension (BP:160/95)`, stays part of
  the name. Two conditions that would give the same column name are told apart
  with `_2`, `_3`.
- Without `-o`, the output is named after the input without `.studio.json`:
  `okafor.studio.json` gives `okafor.mped`, where 0.1.0 wrote
  `okafor.studio.mped`.
- Within each generation, people are listed in the order of the drawing,
  from left to right, rather than in the order of Pedigree Studio's internal
  ids.
- Session files are read as UTF-8 (with or without a byte-order mark) and the
  PED files written as UTF-8, whatever the computer's own setting, so names
  with accents no longer fail on Windows.
- `-d` makes the output folder if it does not exist. In 0.1.0 the README's own
  example (`-d ./output/`) failed unless the folder was already there, and
  the error said that the input file could not be found.
- `studio2ped_standalone.py` is made from the package by
  `tools/make_standalone.py`, and a test checks that it is up to date and
  writes exactly what the package writes.
- New in the Python interface: `convert(..., ids=...)`,
  `convert_file(..., ids=...)`, `individual_ids`, `pedigree_numbers` and
  `ID_CHOICES`; `ConversionResult` has `notes` and `ids`.
- `--version`, tests run on Python 3.9 to 3.14, and releases are published to
  PyPI from GitHub.

Commands written for 0.1.0 still run unchanged. To get 0.1.0's identifiers,
add `--ids text`.

## 0.1.0

Released on PyPI on 20 May 2026.
