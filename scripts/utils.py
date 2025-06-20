import shutil
import subprocess
from pathlib import Path
from typing import Dict, Tuple, Union, Optional
import numpy as np
from bids.layout import parse_file_entities
from pyrelimri import similarity
from niworkflows.func.util import init_skullstrip_bold_wf
from pathlib import Path
import pandas as pd
from nilearn.image import load_img, math_img, new_img_like


def voxel_inout_ratio(img_path: str, mask_path: str) -> Tuple[float, float, float]:
    """
    Calculates the percentage of non-zero voxels inside and outside a brain mask 
    for a given image.

    Parameters:
    img_path (str): Path to the NIfTI image file.
    mask_path (str): Path to the corresponding brain mask (same space).

    Returns:
    percent_inside (float): Percentage of non-zero voxels inside the brain mask.
    percent_outside (float): Percentage of non-zero voxels outside the brain mask.
    ratio_invout (float): Ratio of inside versus outside percentage.
    """
    img_nifti = load_img(img_path)
    mask_nifti = load_img(mask_path)

    # Extract numpy arrays & get nonzeros
    img_data = img_nifti.get_fdata()
    mask_data = mask_nifti.get_fdata() > 0      
    nonzero_inside = np.count_nonzero(img_data[mask_data])
    nonzero_outside = np.count_nonzero(img_data[~mask_data])
    total_nonzero = nonzero_inside + nonzero_outside

    # Calculate percentages and ratio
    percent_inside = (nonzero_inside / total_nonzero) * 100 if total_nonzero != 0 else 0
    percent_outside = (nonzero_outside / total_nonzero) * 100 if total_nonzero != 0 else 0
    ratio_invout = percent_inside / percent_outside if percent_outside != 0 else float('inf')

    return percent_inside, percent_outside, ratio_invout


def similarity_boldtarget_metrics(img_path: Path, brainmask_path: Path, n_extreme_voxels: int):
    """
    Calculate similarity metrics between a BOLD image and a target brain mask.

    Parameters:
    img_path (Path): Path to the BOLD image file.
    brainmask_path (Path): Path to the brain mask file.
    n_extreme_voxels (int): Number of extreme value voxels to report.

    Returns:
    dict: Dictionary containing various similarity metrics:
        - img1: Subject run information
        - img1name: Image filename
        - img2: Reference space name
        - dice: DICE similarity score
        - voxinmask: Percentage of voxels inside mask
        - voxoutmask: Percentage of voxels outside mask
        - ratio_inoutmask: Ratio of inside to outside voxels
        - numvox_grtr_1e10: Number of extreme value voxels
    """
    # Parse filename to extract BIDS info
    parsed_dat = parse_file_entities(img_path)
    parts = []
    for key in ['subject', 'session', 'task', 'run']:
        if key in parsed_dat:
            parts.append(f"{key}-{parsed_dat[key]}")

    sub_run_info = '_'.join(parts)
    
    # Calculate dice similarity
    dice_est = similarity.image_similarity(
        imgfile1=img_path,
        imgfile2=brainmask_path,
        mask=None,
        thresh=None,
        similarity_type='dice'
    )

    # Calculate voxel ratios
    perc_in, perc_out, inout_ratio = voxel_inout_ratio(
        img_path=str(img_path), 
        mask_path=str(brainmask_path)
    )

    # Return results as a dictionary
    return {
        "img1": sub_run_info,
        "img1name": img_path.name,
        "img2": "mni152",
        "dice": dice_est,
        "voxinmask": perc_in,
        "voxoutmask": perc_out,
        "ratio_inoutmask": inout_ratio,
        "numvox_grtr_1e10": n_extreme_voxels
    }
    

def boldmask_to_targetspace(boldmask, fov_mask, t1w_to_mni_file, boldref_to_t1w_file, mni_template, output_tmp):
    """
    Transform a BOLD reference image to target MNI space using ANTs.

    Parameters:
    boldmask (str or Path): Path to the BOLD mask image.
    fov_mask (str or Path): Path to the BOLD FOV mask image.
    t1w_to_mni_file (str or Path): Path to the T1w to MNI transformation file.
    boldref_to_t1w_file (str or Path): Path to the BOLD to T1w transformation file.
    mni_template (str or Path): Path to the MNI template reference image.
    output_tmp (str or Path): Path to the output directory.

    Returns:
    success (bool): True if the transformation was successful, False otherwise.
    output_image (Path): Path to the transformed image.
    """
    try:
        refmask = Path(boldmask)
        fovmask = Path(fov_mask)
        t1w_to_mni = Path(t1w_to_mni_file)
        boldref_to_t1w = Path(boldref_to_t1w_file)
        output_tmp = Path(output_tmp)    
        output_tmp.mkdir(parents=True, exist_ok=True)

        masks = {"refmask": refmask, "fovmask": fovmask}
        outputs = {}

        for mask_name, mask_path in masks.items():
            print(f"Processing {mask_name}: {mask_path}")
            
            # Create consistent output filename
            insert_str = "_space-MNI152NLin2009cAsym"
            base_name = mask_path.stem.replace('.nii', '')  # Handle .nii.gz properly
            out_file_name = f"{base_name}_{mask_name}{insert_str}.nii.gz"
            output_image = output_tmp / out_file_name
            
            print(f"  Output: {output_image}")

            # Build ANTs command
            cmd = [
                "antsApplyTransforms",
                "--default-value", "0",
                "--float", "1",
                "--input", str(mask_path),
                "--reference-image", str(mni_template),
                "--output", str(output_image),
                "--interpolation", "Linear",
                "--transform", str(t1w_to_mni),
                "--transform", str(boldref_to_t1w)
            ]
            
            print(f"Running ANTs command for {mask_name}:")
            print(" ".join(cmd))
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                print(f"Error running antsApplyTransforms:\n{result.stderr}")
                return False, {}
            else:
                print(f"antsApplyTransforms completed: {output_image}")
                outputs[mask_name] = output_image 
        
        return True, outputs
    
    except Exception as e:
        print(f"Error processing {boldref_file}: {str(e)}")
        return False, outputs


def extract_brain(brain_image, output_tmp):
    """
    Extract brain from a brain image.

    Parameters:
    brain_image (Path): Path to the brain native or MNI space image.
    output_tmp (Path): Path to the output directory.

    Returns:
    tuple: (success (bool), brain_image (Path), mask_path (Path or None))
    """
    try:
        subject_output_dir = Path(output_tmp)
        wf_dir = subject_output_dir / "working"
        wf_dir.mkdir(parents=True, exist_ok=True)

        wf = init_skullstrip_bold_wf(name="skullstrip_bold_wf")
        wf.base_dir = str(wf_dir)
        wf.inputs.inputnode.in_file = str(brain_image)
        result = wf.run()

        # Prepare mask filename
        brain_image = Path(brain_image)
        bold_base = brain_image.name[:-7]
        mask_name = bold_base + "_mask.nii.gz"
        mask_target = subject_output_dir / mask_name

        # Find and copy mask file
        for node in result.nodes:
            if "skullstrip" in node.name:
                outputs = node.result.outputs.get()
                mask_file = outputs.get('mask_file')
                
                # Check for mask_file in outputs if not directly available
                if not mask_file:
                    for key in outputs:
                        if key.endswith('mask_file') and outputs[key]:
                            mask_file = outputs[key]
                            break
                
                if mask_file and Path(mask_file).exists():
                    shutil.copy(mask_file, mask_target)
                    print(f"Brain mask copied to: {mask_target}")
                    return True, brain_image, mask_target

        print("No brain mask found.")
        return False, brain_image, None

    except Exception as e:
        print(f"Error in brain extraction: {str(e)}")
        return False, brain_image, None


def process_subject_run(sub, taskname, sess, runnum, fmriprep_deriv_layout, mni_template, mni_mask, deriv_type, output_dir):
    """
    Process a single subject's run for QC metrics.
    
    Parameters:
    sub (str): Subject ID.
    taskname (str): Task name.
    sess (str or None): Session ID or None if not available.
    runnum (str or None): Run number or None if not available.
    fmriprep_deriv_layout: BIDS layout object.
    mni_template (Path): Path to MNI template image.
    mni_mask (Path): Path to MNI mask image.
    deriv_type (str): Type of fmriprep derivative ('minimal' or 'non-minimal').
    output_dir (Path): Output directory path.
    
    Returns:
    dict or None: QC metrics if successful, None otherwise.
    """
    if deriv_type not in ["minimal", "non-minimal"]:
        raise ValueError("deriv_type must be 'minimal' or 'non-minimal'")
   
    # 1. Get transform files
    to_t1w_files = fmriprep_deriv_layout.get(
        subject=sub,
        task=taskname,
        session=sess,
        run=runnum,
        return_type='file',
        extension=".txt", 
        suffix="xfm",
        desc="coreg" if deriv_type == "minimal" else None,
        to="T1w",
        mode="image"
    )
    print(f"to_t1w_files found: {sub} {taskname} {sess} {runnum} - {len(to_t1w_files)}")

    if not to_t1w_files:
        return None
    
    # 2. Get T1w-to-MNI transform files
    t1w_to_mni_files = fmriprep_deriv_layout.get(
        subject=sub,
        return_type='file',
        extension=".h5",
        suffix="xfm",
        to="MNI152NLin2009cAsym",
        mode="image"
    )
    print(f"t1w_to_mni_files found: {sub} {taskname} {sess} - {len(t1w_to_mni_files)}")
    
    if not t1w_to_mni_files:
        return None
    
    # 3. Get boldref images
    boldref_files = fmriprep_deriv_layout.get(
        subject=sub,
        task=taskname,
        session=sess,
        run=runnum,
        return_type='file',
        suffix="boldref",
        desc="coreg" if deriv_type == "minimal" else None,
        extension=".nii.gz"
    )
    print(f"boldref_files found: {sub} {taskname} {sess} {runnum} - {len(boldref_files)}")
    
    if not boldref_files:
        return None

    # Create FOV image using boldref
    boldref = load_img(boldref_files[0])
    fov_img = new_img_like(boldref, np.ones(boldref.shape, dtype='u1'))
    
    boldref_path = Path(boldref_files[0])
    base_name = boldref_path.name[:-7] if boldref_path.name.endswith('.nii.gz') else boldref_path.stem
    fov_output_path = boldref_path.parent / f"{base_name}_fov.nii.gz"
    fov_img.to_filename(str(fov_output_path))
    
    # Calculate extreme values (occurs in minimal when voxels are noise)
    out_data = boldref.get_fdata()
    num_extreme_voxels = np.sum(np.abs(out_data) > 1e10)
    
    # Extract brain
    brain_extract_success, brain_out_image, brain_mask = extract_brain(
        brain_image=boldref_path, 
        output_tmp=output_dir
    )
    
    if not brain_extract_success:
        bold_base = boldref_path.name[:-7]
        mask_name = bold_base + "_mask.nii.gz"
        brain_mask = Path(output_dir) / mask_name
        binary_img = math_img('img > 0', img=boldref)
        binary_img_conj = math_img('subbin*mnimask', subbin=binary_img, mnimask=mni_mask)
        binary_img_conj.to_filename(brain_mask)
    
    # Transform BOLD FOV and brain masks to target space
    ants_success, output_imgs = boldmask_to_targetspace(
        boldmask=brain_mask,
        fov_mask=fov_output_path, 
        t1w_to_mni_file=t1w_to_mni_files[0], 
        boldref_to_t1w_file=to_t1w_files[0], 
        mni_template=mni_template, 
        output_tmp=output_dir
    )

    # Constrain MNI mask with BOLD FOV
    fov_base_name = fov_output_path.name[:-7] if fov_output_path.name.endswith('.nii.gz') else fov_output_path.stem
    constrained_mask = Path(output_dir) / f"{fov_base_name}_tpl-MNI152NLin2009cAsym-mask-constrained.nii.gz"
    fov_mni_mask = math_img('subbin*mnimask', subbin=output_imgs['fovmask'], mnimask=mni_mask)
    fov_mni_mask.to_filename(str(constrained_mask))

    # Calculate QC metrics
    qc_brain_checks = similarity_boldtarget_metrics(
        img_path=output_imgs['refmask'], 
        brainmask_path=constrained_mask, 
        n_extreme_voxels=num_extreme_voxels
    )
    
    return qc_brain_checks
