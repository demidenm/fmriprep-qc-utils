#!/bin/bash
set -euo pipefail

# Check for required arguments
if [ $# -lt 1 ]; then
  echo "Usage: $0 <openneuro_id>"
  echo "Example: $0 ds000102"
  exit 1
fi

# -------------------- Set Paths / Variables --------------------
# Get command line arguments
openneuro_id=$1 # OpenNeuro ID, e.g. ds000102

# Set paths from config file
relative_path=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
config_file=$(realpath "${relative_path}/../path_config.json")

# config file exists
if [ ! -f "$config_file" ]; then
  echo "Error: Config file not found at $config_file"
  exit 1
fi

# Extract values using jq
data_dir=$(jq -r '.fmriprep_derivatives_dir' "$config_file")
repo_dir=$(jq -r '.code_repo' "$config_file")
scripts_dir="${repo_dir}/scripts"
scratch_out=$(jq -r '.tmp_folder' "$config_file")
output_dir=$(jq -r '.output_dir' "$config_file")
mask_path="${repo_dir}/mni_brain"

# activate uv virtual env which sets paths for afni/ants, too
source ${repo_dir}/.venv/bin/activate

# make scratch and data dir if not present
mkdir -p "${scratch_out}"
mkdir -p "${output_dir}"

# -------------------- Run Check Script --------------------
echo "#### Running minimal_derivs_check.py ####"
echo -e "\tStudy ID: ${openneuro_id}"
echo -e "\tFMRIPrep Directory: ${data_dir}"
echo -e "\tOutput Directory: ${output_dir}"
echo -e "\tScratch Output: ${scratch_out}"
echo

sleep 2

# check whether preproc bold volumetric data exists, if it does, data are NOT minimal derivatives.

if find "${data_dir}/${openneuro_id}/sub-*" -name "*space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz" -print -quit 2>/dev/null | grep -q .; then
    minimal_derivatives="no"
    echo -e "Found complete derivatives with MNI152 space files\n"
else
    minimal_derivatives="yes"
    echo -e "⚠️  Only minimal derivatives available\n"
fi

cd ${scratch_out}

if [ "$minimal_derivatives" = "yes" ]; then
  uv --project "${repo_dir}" run python \
      "${scripts_dir}/minimal_derivs_check.py" \
      --openneuro_study "${openneuro_id}" \
      --derivs_path "${data_dir}/${openneuro_id}" \
      --mask_dir "${mask_path}" \
      --outdir "${output_dir}" \
      --tmpdir "${scratch_out}"
else
    uv --project "${repo_dir}" run python \
      "${scripts_dir}/full_derivs_check.py" \
      --openneuro_study "${openneuro_id}" \
      --derivs_path "${data_dir}/${openneuro_id}" \
      --mask_dir "${mask_path}" \
      --outdir "${output_dir}" \
      --tmpdir "${scratch_out}"
fi

cd ${scripts_dir}