# studio2ped

Convert Pedigree Studio session JSON files into standard PED pedigree files or extended MPED (multi-phenotype PED) files.

## Installation

```bash
pip install studio2ped
```

Or use the standalone script (`studio2ped_standalone.py`) with no installation required — needs only Python 3.9+.

## Usage

### Command line

```bash
# Basic conversion
studio2ped session.json

# Specify output name and directory
studio2ped session.json -o my_pedigree -d ./output/

# Using the standalone script
python studio2ped_standalone.py session.json
```

### Python API

```python
import studio2ped

# From a session dict
import json
with open("session.json") as f:
    session = json.load(f)

result = studio2ped.convert(session)
print(result.summary)
for filename, content in result.files:
    print(f"--- {filename} ---")
    print(content)

# From file to file
result = studio2ped.convert_file("session.json")
for filepath, _ in result.files:
    print(f"Written: {filepath}")
```

## What It Does

The converter reads a Pedigree Studio session JSON file and:

1. **Detects separate pedigrees** — if the canvas contains multiple unconnected family trees, each is exported as a separate file
2. **Resolves family structure** via graph traversal through partnerships and child links — not spatial position (so rearranged pedigrees convert correctly)
3. **Extracts phenotypes** from the legend/colour key: solid fills, half fills, quartered fills, and shading patterns are all recognised
4. **Detects carrier notation** — centre dots (●) and half-filled shapes are identified as carrier status
5. **Chooses the right format** automatically:
   - **Single phenotype** → standard `.ped` file (6 columns)
   - **Multiple phenotypes** or **carrier notation alongside a phenotype** → extended `.mped` file

## Output Formats

### Standard PED (`.ped`)

The standard 6-column format used by PLINK, GATK, and most genetics tools:

```
# FamID  IndID  FatherID  MotherID  Sex  Phenotype
FAM1     John   0         0         1    1
FAM1     Mary   0         0         2    1
FAM1     Alice  John      Mary      2    2
```

Phenotype codes: `0` = unknown, `1` = unaffected, `2` = affected.

### Extended MPED (`.mped`)

A multi-phenotype extension for pedigrees with more than one condition tracked. The format adds a header line naming the phenotype columns and supports carrier status:

```
# MPED v1	Breast_cancer	Carrier
# FamID	IndID	FatherID	MotherID	Sex	Breast_cancer	Carrier
FAM1	John	0	0	1	1	1
FAM1	Mary	0	0	2	1	3
FAM1	Alice	John	Mary	2	2	1
```

Phenotype codes: `0` = unknown, `1` = unaffected, `2` = affected, `3` = carrier.

The MPED format is designed to be easily parseable: the first line declares the format and phenotype column names, the second line is a human-readable column header, and data lines follow the same tab-delimited structure as standard PED with additional columns.

## Phenotype Detection

The converter maps Pedigree Studio's visual markers to phenotype status using the legend/colour key:

| Visual Marker | Legend Key Format | Status |
|---------------|-------------------|--------|
| Solid colour fill | `#rrggbb` | Affected (2) |
| Full shading (stripes/dots) | `shading:pattern:full` | Affected (2) |
| Half colour fill (one side only) | `#rrggbb` | Carrier (3) |
| Half shading | `shading:pattern:half-left` | Carrier (3) |
| Quartered fill (any quarter) | `#rrggbb` | Affected (2) |
| Centre dot (●) | — | Carrier (3) |
| No fill | — | Unaffected (1) |

Phenotype names are taken from the text the user typed into the legend (e.g., "Breast cancer", "Carrier status"). If the legend has no text for an entry, that visual marker is ignored.

## Multiple Pedigrees

If a session contains multiple unconnected pedigrees (common when a user draws several families on the same canvas), the converter detects each connected component via graph traversal and exports them as separate files:

```
pedigree_1.ped    # First family
pedigree_2.ped    # Second family
pedigree_3.mped   # Third family (if multi-phenotype)
```

## Individual IDs

The converter generates individual IDs in priority order:

1. **Custom freetext label** (if the user edited the numbering label)
2. **First line of annotation text** (the text below each shape)
3. **Pedigree Studio internal ID** (fallback, e.g. `p-3`)

IDs are sanitised to remove whitespace and special characters.

## License

MIT
