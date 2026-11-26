# nepal-hydro

WECS/DHM (1990) and MIP (1982) hydrology for ungauged rivers in Nepal.

**Work in progress (v0.1.0 under construction).** See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
for the full spec. The quickstart, the Solu Khola example and the engineering disclaimer land in a
later step.

## Known caveats

Three items in the guideline scan could not be read cleanly. They are implemented
as the spec describes and are awaiting review against a clean printed copy:

- **WECS/DHM flow duration Q80 and Q100:** the forms are reconstructed from the
  Solu Khola worked example (the only forms that reproduce its Q80 = 3.00 and
  Q100 = 1.78). They do not warn on each call.
- **MIP region 4 ordinates:** separated from an interleaved scan (July and October
  both read 6.89). Using region 4 emits `UnverifiedCoefficientWarning`.

`nepal_hydro.coefficients.unverified()` lists every flagged item with its note.
