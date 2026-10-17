# studio2ped

Convert families drawn in [Pedigree Studio](https://github.com/comparativechrono/PedigreeStudio)
into standard PED pedigree files, or into extended MPED (multi-phenotype PED)
files when more than one condition is recorded.

## Installation

```bash
pip install studio2ped
```

It needs Python 3.9 or later and nothing else. You can also use the
standalone script, `studio2ped_standalone.py`, without installing anything.

## Usage

### Command line

```bash
# Basic conversion: writes okafor.ped, or okafor.mped if the family needs MPED
studio2ped okafor.studio.json

# Specify output name and directory
studio2ped okafor.studio.json -o my_pedigree -d ./output/

# Identify people by the labels the drawing shows, instead of pedigree numbers
studio2ped okafor.studio.json --ids drawing

# Using the standalone script
python studio2ped_standalone.py okafor.studio.json
```

The command prints a short summary, the files it wrote and notes on anything
you should know: symbols that are not people and were left out, identifiers
that had to be changed, and so on.

Commands written for version 0.1.0 still work. The difference you will notice
is that people are now identified by their pedigree numbers; add `--ids text`
to get the identifiers 0.1.0 used (see [Identifying people](#identifying-people)).

### Python API

```python
import json
import studio2ped

with open("okafor.studio.json", encoding="utf-8") as f:
    session = json.load(f)

result = studio2ped.convert(session, "okafor")     # ids="drawing", "studio" or "text" to choose identifiers
print(result.summary)
for note in result.notes:
    print("Note:", note)
for filename, content in result.files:
    print(f"--- {filename} ---")
    print(content)

# From file to file
result = studio2ped.convert_file("okafor.studio.json")
for filepath, _ in result.files:
    print(f"Written: {filepath}")
```

## What it does

The converter reads a Pedigree Studio session file and:

1. **Detects separate pedigrees**: if the canvas holds several unconnected
   families, each is written to a file of its own.
2. **Works out the family structure** from the partnership and child lines,
   not from where the symbols are, so a rearranged pedigree converts correctly.
3. **Leaves out symbols that are not people.** Pedigree Studio stores the "no
   children" bar and the "infertility" double bar as children of the couple;
   they are not written as individuals, and a note names the couple.
4. **Extracts phenotypes** from the colour key: solid fills, half fills,
   quartered fills and shading patterns are all recognised.
5. **Detects carrier notation**: centre dots (●) and half-filled symbols mark
   carriers.
6. **Chooses the format**:
   - **one phenotype** → a standard `.ped` file (6 columns);
   - **several phenotypes**, or **carrier notation alongside a phenotype** → an
     extended `.mped` file.

## Identifying people

| `--ids` | Each person is identified by |
|---|---|
| `numbers` (the default) | their pedigree number as Pedigree Studio shows it: the generation in Roman numerals and the position from the left, such as `II-3` |
| `drawing` | the label the drawing shows under its numbering setting: pedigree numbers, letters (`II-C`, or `A`, `B`, `C` …) or labels typed in |
| `studio` | Pedigree Studio's own id, such as `p-3` |
| `text` | what version 0.1.0 used: the label typed in if there is one, otherwise the first line of the text under the symbol, otherwise Pedigree Studio's id |

Pedigree numbers are the ones studio2ga4gh writes into the GA4GH files, so a
person can be followed from one file to the other. The text under a symbol
usually holds a name and an age ("Alice, 50"), so `text`, and `drawing` when
the drawing has labels typed in, can put names into the file: use them only
when that is acceptable for wherever the file is going.

Identifiers can't contain spaces, so spaces become underscores and other
punctuation is dropped. No two people may share an identifier, and `0` means
"no parent" in a PED file, so if a label would be shared by two people (two
cousins both labelled "26", say), would be empty or would be `0`, the person
is given their pedigree number instead, and a note says so.

Pedigree numbers follow the drawing, as in Pedigree Studio: a new generation
starts 80 pixels or more below the first symbol of the generation above, and
the "no children" and "infertility" symbols are counted in their row, even
though they are not written to the file.

## Output formats

### Standard PED (`.ped`)

The standard 6-column format used by PLINK, GATK and most genetics tools:

```
# Family: FAM1
# FamID  IndID  FatherID  MotherID  Sex  Phenotype
FAM1     I-1    0         0         1    1
FAM1     I-2    0         0         2    1
FAM1     II-1   I-1       I-2       2    2
```

Phenotype codes: `0` = unknown, `1` = unaffected, `2` = affected. The columns
are separated by tabs.

### Extended MPED (`.mped`)

A multi-phenotype extension for pedigrees in which more than one condition is
tracked. It adds a header line naming the phenotype columns, and a carrier
status:

```
# MPED v1	Breast_cancer	Carrier
# FamID	IndID	FatherID	MotherID	Sex	Breast_cancer	Carrier
FAM1	I-1	0	0	1	1	1
FAM1	I-2	0	0	2	3	3
FAM1	II-1	I-1	I-2	2	2	1
```

Phenotype codes: `0` = unknown, `1` = unaffected, `2` = affected, `3` = carrier.

The format is easy to read by program: the first line declares the format and
names the phenotype columns, the second is a header for people to read, and
the data lines have the same tab-separated columns as standard PED, with one
more column for each phenotype.

Column names are the condition names from the colour key, with spaces turned
into underscores. An ontology id written in brackets after a name, as
studio2ga4gh reads it ("Breast cancer [MONDO:0007254]"), is left out of the
column name, which is then `Breast_cancer`, and a note says which id it had.
If two conditions would give the same column name, the second becomes
`Breast_cancer_2`.

## Phenotype detection

The converter maps Pedigree Studio's markings to phenotype status using the
colour key:

| Marking | Colour key entry | Status |
|---------------|-------------------|--------|
| Solid colour fill | `#rrggbb` | Affected (2) |
| Full shading (stripes/dots) | `shading:pattern:full` | Affected (2) |
| Half colour fill (one side only) | `#rrggbb` | Carrier (3) |
| Half shading | `shading:pattern:half-left` | Carrier (3) |
| Quartered fill (any quarter) | `#rrggbb` | Affected (2) |
| Centre dot (●) | — | Carrier (3) |
| No fill | — | Unaffected (1) |

Phenotype names are the text typed into the colour key (for example "Breast
cancer"). A colour with no text in the key is ignored.

A centre dot gives 3 in the Carrier column, and in the column of the condition
the person is drawn with; on a symbol with no fill it is the first condition
in the key.

## Multiple pedigrees

If a drawing holds several unconnected families (common when several are
drawn on the same canvas), each is written to a file of its own:

```
okafor_1.mped    # the first family
okafor_2.mped    # the second family
```

The colour key belongs to the whole drawing, so every family is written in the
same format: all `.ped` or all `.mped`.

## The standalone script

`studio2ped_standalone.py` is the whole package in one file, for computers
where installing a package is awkward; it takes the same options as the
`studio2ped` command. It is made from the package by
`python tools/make_standalone.py`, and a test checks that the two agree.

## Development

```bash
pip install -e ".[test]"
pytest
```

## Licence

MIT
