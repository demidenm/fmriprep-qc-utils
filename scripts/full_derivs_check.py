import argparse
import os
import pandas as pd
import numpy as np
from bids import BIDSLayout
from pathlib import Path
from utils import process_subject_run_full

# Set up argument parsing
parser = argparse.ArgumentParser(description="Setup OpenNeuro study variables")
parser.add_argument("--openneuro_study", type=str, required=True, help="OpenNeuro study ID (e.g ds000124)")
parser.add_argument("--derivs_path", type=str, required=True, help="Path to the fmriprep derivatives")
parser.add_argument("--mask_dir", type=str, required=True, help="Repo MNI mask directory path")
parser.add_argument("--outdir", type=str, required=True, help="Directory where to save resulting QC pd.DataFrame")
parser.add_argument("--tmpdir", type=str, required=True, help="Directory where to run analyses")

args = parser.parse_args()

# Assign arguments to variables using pathlib
study_id = args.openneuro_study
derivs_path = Path(args.derivs_path).resolve()
mask_dir = Path(args.mask_dir)
output_dir = Path(args.outdir).resolve()
tmp_dir = Path(args.tmpdir).resolve()

# change where crash logs / study working outputs go in scratch
tmp_study = tmp_dir / study_id
tmp_study.mkdir(parents=True, exist_ok=True)
os.environ["NIPYPE_CRASHFILE_DIR"] = str(tmp_study)


# Load MNI mask
mni_mask = mask_dir / "tpl-MNI152NLin2009cAsym_res-02_desc-brain_mask.nii.gz"

# Build layout
print("Building layout... for", study_id, "\n\t",derivs_path)
fmrirepderiv_layout = BIDSLayout(derivs_path, validate=False)

df_qcresults = process_subject_run_full(fmrilayout=fmrirepderiv_layout, mni_mask=mni_mask, output_dir=output_dir)
if df_qcresults.empty:
    raise ValueError("Error: df_qcresults is empty. No QC results found.")

# flag if similarity is lower than .80 or voxoutmask are 
df_qcresults["flagged"] = (
    (df_qcresults["dice"] < 0.80) | (df_qcresults["voxoutmask"] > 20) | (df_qcresults["numvox_grtr_1e10"] > 0)
).astype(int)

filename = f"study-{study_id}_check-bold_fmriprep-nonminimal.tsv"
df_qcresults.to_csv(output_dir / filename, sep='\t', index=False)
print(f"Results saved to {output_dir / filename}")
