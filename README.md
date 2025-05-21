# fMRIPrep Derivatives Quality Checker

This repository contains tools to perform quality checks on fMRIPrep processed neuroimaging data, supporting both full and minimal derivatives formats.

## Environment Setup

This project uses `uv` for Python environment management. To set up the required environment and dependencies:

```bash
./setup.sh
```

The setup script will:
1. Install `uv` if not already available
2. Install required system dependencies (tcsh, jq)
3. Download and install AFNI locally (installs into ./tools/)
4. Set up ANTs through a conda environment
5. Configure environment activation (.venv/source/activate) to include AFNI and ANTs in the path
6. uv sync the Python environment with required packages

## Overview

The quality checking scripts assess the accuracy of spatial normalization by comparing subject-level brain masks in MNI152NLin2009cAsym space with the reference target mask. The checks include:

- Dice coefficient similarity between subject-level and reference brain masks
- Percentage of voxels inside/outside the mask
- Detection of unrealistic intensity values (>1e10)

## Usage

Run the quality check with:

```bash
./run_derivatives_check.sh <openneuro_folder>
```

Example:
```bash
./run_derivatives_check.sh ds000009-fmriprep
```

The script automatically determines whether to run the full or minimal derivatives check based on the available data files.

## How It Works

### Detection of Dataset Type

The script automatically detects whether to use the full or minimal derivatives check by searching for preprocessed BOLD files in MNI space:

```bash
find "${data_dir}/${openneuro_id}/sub-*" -name "*space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz" -print -quit 2>/dev/null | grep -q .
```

### Minimal Derivatives Check (`minimal_derivs_check.py`)

For datasets with minimal derivatives, the script:

1. Uses `BIDSLayout` to find for each subject, task, session and run:
   - Coregistration transform files (.txt)
   - MNI152NLin2009cAsym transform files (.h5)
   - Coregistered BOLD reference files (.nii.gz)

2. Transforms the subject's coregistered BOLD reference file to MNI152NLin2009cAsym space

3. Performs brain extraction using the same approach as fMRIPrep:
   ```python
   from niworkflows.func.util import init_skullstrip_bold_wf
   ```

4. Checks for extreme voxel values (>1e10)

5. Calculates the Dice coefficient between the subject's MNI space brain mask and the target space brain mask

6. Determines how many voxels in the subject's brain mask fall outside the target mask

### Full Derivatives Check (`full_derivs_check.py`)

For datasets with full derivatives, the script:

1. Uses `BIDSLayout` to find all MNI152NLin2009cAsym space resolution-2 brain mask files (.nii.gz)

2. Directly calculates:
   - Dice similarity coefficient between subject masks and the target mask
   - Percentage of voxels outside the target mask

### Output

Results are saved to:
```
{repo_dir}/results/study-{id}_check-bold_fmriprep-{minimal/nonminal}.tsv
```

The output TSV file contains:
- `img1`: Subject, task, run, session information
- `img1name`: Full image filename
- `img2`: MNI152 target (same for all subjects)
- `dice`: Dice similarity between img1 and img2
- `voxinmask`: Percentage of voxels in mask
- `voxoutmask`: Percentage of voxels outside mask
- `ratio_inoutmask`: Ratio of in/out mask voxels
- `numvox_grtr_1e10`: Number of voxels with values >1e10
- `flagged`: Indicates quality issues (TRUE if dice <0.80, voxoutmask >20%, or any voxels >1e10)

