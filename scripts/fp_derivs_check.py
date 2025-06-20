import argparse
import os
import pandas as pd
import numpy as np
from bids import BIDSLayout
from pathlib import Path
from utils import (voxel_inout_ratio, boldmask_to_targetspace,
extract_brain, process_subject_run)

# Set up argument parsing
parser = argparse.ArgumentParser(description="Setup OpenNeuro study variables")
parser.add_argument("--openneuro_study", type=str, required=True, help="OpenNeuro study ID (e.g ds000124)")
parser.add_argument("--derivs_path", type=str, required=True, help="Path to the fmriprep derivatives")
parser.add_argument("--mask_dir", type=str, required=True, help="Repo MNI mask directory path")
parser.add_argument("--deriv_type", type=str, required=True, help="Derivatives type, minimal/non-minimal")
parser.add_argument("--outdir", type=str, required=True, help="Directory where to save resulting QC pd.DataFrame")
parser.add_argument("--tmpdir", type=str, required=True, help="Directory where to run analyses")

args = parser.parse_args()

# Assign arguments to variables


# Assign arguments to variables using pathlib
study_id = args.openneuro_study
derivs_path = Path(args.derivs_path).resolve()
mask_dir = Path(args.mask_dir)
derivtype = args.deriv_type
output_dir = Path(args.outdir).resolve()
tmp_dir = Path(args.tmpdir).resolve()

# change where crash logs / study working outputs go in scratch
tmp_study = tmp_dir / study_id
tmp_study.mkdir(parents=True, exist_ok=True)
os.environ["NIPYPE_CRASHFILE_DIR"] = str(tmp_study)


# Load MNI template and mask
mni_template = mask_dir / "tpl-MNI152NLin2009cAsym_res-02_desc-brain_T1w.nii.gz"
mni_mask = mask_dir / "tpl-MNI152NLin2009cAsym_res-02_desc-brain_mask.nii.gz"

# Build layout
print("Building layout... for", study_id, "\n\t",derivs_path)
fmrirepderiv_layout = BIDSLayout(derivs_path, validate=False)

# Set empty list and grab tasks in OpenNeuro to iterate over
qc_results = []
task_list = fmrirepderiv_layout.get_tasks()

for taskname in task_list:
    subj_list = fmrirepderiv_layout.get_subjects(task=taskname)
    
    for sub in subj_list:
        print("Working on:", sub, taskname)
        session_list = [None]  # Default to None
        if 'session' in fmrirepderiv_layout.get_entities():
            sessions = fmrirepderiv_layout.get_sessions(subject=sub, task=taskname)
            if sessions:
                session_list = sessions
        
        for sess in session_list:
            run_list = [None]  # Default to None
            if 'run' in fmrirepderiv_layout.get_entities():
                runs = fmrirepderiv_layout.get_runs(subject=sub, session=sess, task=taskname)
                if runs:
                    run_list = runs
            
            for runnum in run_list:
                qc_result = process_subject_run(
                    sub=sub,
                    taskname=taskname,
                    sess=sess,
                    runnum=runnum,
                    fmriprep_deriv_layout=fmrirepderiv_layout,
                    deriv_type=derivtype,
                    mni_template=str(mni_template),
                    mni_mask=str(mni_mask),
                    output_dir=str(tmp_study)
                )
                
                if qc_result:
                    qc_results.append(qc_result)

# Combine results into DataFrame
df_qcresults = pd.DataFrame(qc_results)
if df_qcresults.empty:
    raise ValueError("Error: df_qcresults is empty. No QC results found.")

    
# flag if similarity is lower than .80 or voxoutmask are 
df_qcresults["flagged"] = (
    (df_qcresults["dice"] < 0.80) | (df_qcresults["voxoutmask"] > 20) | (df_qcresults["numvox_grtr_1e10"] > 0)
).astype(int)

filename = f"study-{study_id}_check-bold_fmriprep-{derivtype}.tsv"
df_qcresults.to_csv(output_dir / filename, sep='\t', index=False)


