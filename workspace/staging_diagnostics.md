# Evaluation Diagnostics

Score: 0.5683 avg Spearman (VenusREM floor: 0.50, your baseline: 0.4449)
Range: 0.0648 (worst) to 0.8575 (best)
Bottom quartile avg: 0.3646 — this is where gains come from
Speed: 2.0s/protein avg, 2,465,767 total mutations scored
Above VenusREM floor by +0.0683. Well done.

**Data available:** VenusREM, S3F_MSA, ESM2_15B predictions + structure data.
**Import:** `from proteingym_data import get_model_scores, get_residue_structure, get_protein_info`
**Reference:** Read `DATA_PRIMER.md` for API details.

## Key Insights

- **Score calibration:** Predicted IQR [-2.2, 0.6] is 0.3× narrower than experimental IQR [-5.2, 2.9]. Your scores are compressed — consider expanding the output range.
- **Error direction:** Balanced (57% negative, median -3.3). No strong directional bias.
- **Worst substitution classes:** positive→positive (n=6, mean err +107.8, mean |err| 107.8); positive→negative (n=7, mean err +71.6, mean |err| 73.1); positive→aromatic (n=2, mean err +65.0, mean |err| 70.1).
- **Best substitution classes:** negative→hydrophobic (n=24, mean |err| 3.3); aromatic→hydrophobic (n=2, mean |err| 3.4) — keep doing what works here.
- **MSA signal inversion:** Shallow MSA proteins (81, avg 0.6139) outperform deep MSA (104, avg 0.5522). The conservation signal may be noisy or misleading for some proteins.
- **Mutation load effect:** Worst proteins avg 32,192 mutations vs best at 3,178. High-mutation-count proteins are scoring worse — the strategy may be diluting signal across too many mutations.
- **Assay type effect:** Best on Stability (0.6398, n=66), worst on Binding (0.4795, n=13). Different assays measure different biophysical properties — your strategy may be tuned for one but not another.
- **Conservation-error correlation:** Errors are larger at conserved positions (mean |err| 90.9) than variable positions (5.1). The conservation signal may be over-weighted at positions that can't tolerate any change.
- **Structural context:** Errors are larger at predicted core positions (mean |err| 47.7) than surface (21.8). Core residues are packed and intolerant of volume/charge changes — consider position-specific penalties based on burial.

## Weakest Proteins (focus here)
  A0A1I9GEU1_NEIME_Kennouche_2019: 0.0648 (MSA=1610, n=922)
  SCN5A_HUMAN_Glazer_2019: 0.1765 (MSA=20160, n=224)
  KCNE1_HUMAN_Muhammad_2023_expression: 0.1804 (MSA=1290, n=2339)
  SPG1_STRSG_Wu_2016: 0.2009 (MSA=3109, n=149360)
  CAS9_STRP1_Spencer_2017_positive: 0.2054 (MSA=5349, n=8117)
  MK01_HUMAN_Brenan_2016: 0.2255 (MSA=3600, n=6809)
  CALM1_HUMAN_Weile_2017: 0.2262 (MSA=1490, n=1813)
  ENVZ_ECOLI_Ghose_2023: 0.2406 (MSA=600, n=1121)
  GCN4_YEAST_Staller_2018: 0.2683 (MSA=350, n=2638)
  ACE2_HUMAN_Chan_2020: 0.2701 (MSA=8050, n=2223)
  F7YBW8_MESOW_Aakre_2015: 0.3015 (MSA=930, n=9192)
  TPK1_HUMAN_Weile_2017: 0.3027 (MSA=2430, n=3181)
  ODP2_GEOSE_Tsuboyama_2023_1W4G: 0.3124 (MSA=500, n=1134)
  TADBP_HUMAN_Bolognesi_2019: 0.3191 (MSA=1211, n=1196)
  CD19_HUMAN_Klesmith_2019_FMC_singles: 0.3266 (MSA=1183, n=3761)
  HECD1_HUMAN_Tsuboyama_2023_3DKM: 0.3377 (MSA=720, n=5586)
  SOX30_HUMAN_Tsuboyama_2023_7JJK: 0.3435 (MSA=570, n=1010)
  HSP82_YEAST_Cote-Hammarlof_2020_growth-H2O2: 0.3557 (MSA=7090, n=2252)
  REV_HV1H2_Fernandes_2016: 0.3627 (MSA=1160, n=2147)
  SYUA_HUMAN_Newberry_2020: 0.3656 (MSA=1400, n=2497)

## Worst Mutations (examples for debugging)

**A0A1I9GEU1_NEIME_Kennouche_2019** (Spearman=0.0648):
  E99A (negative→hydrophobic): pred=+0.9, exp=-6.7
  P123R (special→positive): pred=+0.3, exp=-6.6
  V33L (hydrophobic→hydrophobic): pred=+0.2, exp=-6.4

**SCN5A_HUMAN_Glazer_2019** (Spearman=0.1765):
  G1631Q (special→polar): pred=-0.2, exp=-205.5
  A1628P (hydrophobic→special): pred=+0.4, exp=-201.7
  I1630S (hydrophobic→polar): pred=+0.4, exp=-185.9

**KCNE1_HUMAN_Muhammad_2023_expression** (Spearman=0.1804):
  L45P (hydrophobic→special): pred=-2.8, exp=+2.1
  L45D (hydrophobic→negative): pred=-2.8, exp=+2.1
  F53Q (hydrophobic→polar): pred=-2.9, exp=+1.9

**SPG1_STRSG_Wu_2016** (Spearman=0.2009):
  V265F:D266 (hydrophobic→hydrophobic): pred=+0.5, exp=+8.8
  V265W:D266 (hydrophobic→hydrophobic): pred=-0.5, exp=+7.3
  V265W:D266 (hydrophobic→special): pred=-0.8, exp=+6.9

**CAS9_STRP1_Spencer_2017_positive** (Spearman=0.2054):
  K755M (positive→hydrophobic): pred=+0.9, exp=-6.5
  N497S (polar→polar): pred=+0.7, exp=-5.7
  G915S (special→polar): pred=+0.4, exp=-5.5

