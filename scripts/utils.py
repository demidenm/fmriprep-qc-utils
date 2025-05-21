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
from nilearn.image import load_img, math_img


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
    

def boldref_to_targetspace(boldref_file, t1w_to_mni_file, boldref_to_t1w_file, mni_template, output_tmp):
    """
    Transform a BOLD reference image to target MNI space using ANTs.

    Parameters:
    boldref_file (str or Path): Path to the BOLD reference image.
    t1w_to_mni_file (str or Path): Path to the T1w to MNI transformation file.
    boldref_to_t1w_file (str or Path): Path to the BOLD to T1w transformation file.
    mni_template (str or Path): Path to the MNI template reference image.
    output_tmp (str or Path): Path to the output directory.

    Returns:
    success (bool): True if the transformation was successful, False otherwise.
    output_image (Path): Path to the transformed image.
    """
    try:
        boldref = Path(boldref_file)
        t1w_to_mni = Path(t1w_to_mni_file)
        boldref_to_t1w = Path(boldref_to_t1w_file)
        output_tmp = Path(output_tmp)
        
        # Create output filename in the output_base_dir
        insert_str = "_space-MNI152NLin2009cAsym_brain"
        base_name = boldref.name[:-7]
        out_file_name = base_name + insert_str + ".nii.gz"
        output_image = output_tmp / out_file_name
        output_image.parent.mkdir(parents=True, exist_ok=True)

        print(f"Processing:")
        print(f"  boldref: {boldref}")
        print(f"  output_image: {output_image}")
        
        # ANTs command
        cmd = [
            "antsApplyTransforms",
            "--default-value", "0",
            "--float", "1",
            "--input", str(boldref),
            "--reference-image", str(mni_template),
            "--output", str(output_image),
            "--interpolation", "Linear",
            "--transform", str(t1w_to_mni),
            "--transform", str(boldref_to_t1w)
        ]

        print("Running command:")
        print(" ".join(cmd))

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error running antsApplyTransforms:\n{result.stderr}")
            return False, output_image
        else:
            print(f"antsApplyTransforms completed: {output_image}")
            return True, output_image
    except Exception as e:
        print(f"Error processing {boldref_file}: {str(e)}")
        return False, output_image
        

def target_extractbrain(mni_image, output_tmp):
    """
    Extract brain from a MNI-space image.

    Parameters:
    mni_image (Path): Path to the MNI-space image.
    output_tmp (Path): Path to the output directory.

    Returns:
    success (bool): True if brain extraction was successful, False otherwise.
    mni_image (Path): Path to the original MNI image.
    mask_path (Path or None): Path to the generated brain mask if successful, None otherwise.
    """
    try:
        subject_output_dir = Path(output_tmp)

        wf_dir = subject_output_dir / "working"
        wf_dir.mkdir(parents=True, exist_ok=True)

        wf = init_skullstrip_bold_wf(name="skullstrip_bold_wf")
        wf.base_dir = str(wf_dir)
        wf.inputs.inputnode.in_file = str(mni_image)
        result = wf.run()

        # Prepare mask filename
        mask_insert = "_mask"
        boldmni_base = mni_image.name[:-7]
        out_mask_name = boldmni_base + mask_insert + ".nii.gz"
        mask_target = subject_output_dir / out_mask_name

        # Find and copy mask file
        found_mask = False
        for node in result.nodes:
            if "skullstrip" in node.name:
                outputs = node.result.outputs.get()
                mask_file = outputs.get('mask_file')
                
                # Search for mask_file in outputs if not directly available
                if not mask_file:
                    for key in outputs:
                        if key.endswith('mask_file') and outputs[key]:
                            mask_file = outputs[key]
                            break
                
                if mask_file and Path(mask_file).exists():
                    found_mask = True
                    shutil.copy(mask_file, mask_target)
                    print(f"Brain mask copied to: {mask_target}")
                    return True, mni_image, mask_target

        print("No brain mask found.")
        return False, mni_image, None

    except Exception as e:
        print(f"Error in brain extraction: {str(e)}")
        return False, mni_image, None



def process_subject_run_minimal(sub, taskname, sess, runnum, fmrirepderiv_layout, mni_template, mni_mask, output_dir):
    """
    Process a single subject's run for QC metrics.
    
    Parameters:
    sub (str): Subject ID.
    taskname (str): Task name.
    sess (str or None): Session ID or None if not available.
    runnum (str or None): Run number or None if not available.
    fmrirepderiv_layout: BIDS layout object.
    mni_template (Path): Path to MNI template image.
    mni_mask (Path): Path to MNI mask image.
    output_dir (Path): Output directory path.
    
    Returns:
    dict or None: QC metrics if successful, None otherwise.
    """
    # 1. Get transform files
    boldref_to_t1w_files = fmrirepderiv_layout.get(
        subject=sub,
        task=taskname,
        session=sess,
        run=runnum,
        return_type='file',
        extension=".txt",
        suffix="xfm",
        desc="coreg",
        to="T1w",
        mode="image"
    )
    print("boldref_to_t1w_files found", sub, taskname, sess, runnum, len(boldref_to_t1w_files))
    
    if not boldref_to_t1w_files:
        return None
    
    # 2. Get T1w-to-MNI transform files
    t1w_to_mni_files = fmrirepderiv_layout.get(
        subject=sub,
        return_type='file',
        extension=".h5",
        suffix="xfm",
        to="MNI152NLin2009cAsym",
        mode="image"
    )
    print("t1w_to_mni_files found from anat", sub, taskname, sess, len(t1w_to_mni_files))
    
    if not t1w_to_mni_files:
        return None
    
    # 3. Get coregistered boldref images
    coreg_boldref_files = fmrirepderiv_layout.get(
        subject=sub,
        task=taskname,
        session=sess,
        run=runnum,
        return_type='file',
        suffix="boldref",
        desc="coreg",
        extension=".nii.gz"
    )
    print("coreg_boldref_files found", sub, taskname, sess, runnum, len(coreg_boldref_files))
    
    if not coreg_boldref_files:
        return None
    
    # Run boldref to target space transformation
    ants_success, mni_path_out = boldref_to_targetspace(
        boldref_file=coreg_boldref_files[0], 
        t1w_to_mni_file=t1w_to_mni_files[0], 
        boldref_to_t1w_file=boldref_to_t1w_files[0], 
        mni_template=mni_template, 
        output_tmp=output_dir
    )
    
    if not ants_success:
        return None
    
    # Count extreme voxels in the output image
    out_img_load = load_img(mni_path_out)
    out_data = out_img_load.get_fdata()
    num_extreme_voxels = np.sum(np.abs(out_data) > 1e10)
    
    # Extract brain and compute QC metrics
    brainextract_success, mni_image, mask_target = target_extractbrain(
        mni_image=mni_path_out, 
        output_tmp=output_dir
    )
    
    if not brainextract_success:
        # Create a fallback mask if brain extraction fails
        mask_insert = "_mask"
        boldmni_base = mni_path_out.name[:-7]
        out_mask_name = boldmni_base + mask_insert + ".nii.gz"
        mask_target = Path(output_dir) / out_mask_name
        binary_img = math_img('img > 0', img=out_img_load)
        binary_img_conj = math_img('subbin*mnimask', subbin=binary_img, mnimask=mni_mask)
        binary_img_conj.to_filename(mask_target)
    
    # Calculate QC metrics
    qc_brain_checks = similarity_boldtarget_metrics(
        img_path=mask_target, 
        brainmask_path=mni_mask, 
        n_extreme_voxels=num_extreme_voxels
    )
    
    return qc_brain_checks


def process_subject_run_full(fmrilayout, mni_mask, output_dir):
    """
    Process a single subject's run for QC metrics.
    
    Parameters:
    fmrilayout: BIDS layout object.
    mni_mask (Path): Path to MNI mask image.
    output_dir (Path): Output directory path.
    
    Returns:
    dict or None: QC metrics if successful, None otherwise.
    """
    

    
    # Calculate QC metrics
    qc_results = []

    mni_brain_runs = fmrilayout.get(
            suffix='mask',
            extension='.nii.gz',
            space='MNI152NLin2009cAsym',
            res=2,
            desc='brain',
            return_type='file'
            )
    try:
        
        for brain_path in mni_brain_runs:
            
            qc_result = similarity_boldtarget_metrics(
                img_path=Path(brain_path), # make sure it is a Path object, parse .name element 
                brainmask_path=mni_mask, 
                n_extreme_voxels=np.nan
            )
            if qc_result:
                qc_results.append(qc_result)

    except Exception as e:
        print(f"Error in similarity_boldtarget_metrics: {str(e)}")


    # return results as pd.DataFrame
    return pd.DataFrame(qc_results)