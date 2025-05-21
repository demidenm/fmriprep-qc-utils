#!/bin/bash

# Exit on error
set -e

# Compare semantic versions
version_ge() { 
    [ "$(printf '%s\n' "$1" "$2" | sort -V | tail -n1)" == "$1" ]
}

TOOLS_DIR="./tools"
AFNI_DIR="${TOOLS_DIR}/afni"

mkdir -p "$TOOLS_DIR"
mkdir -p "./results"

# === Check for uv ===
if ! command -v uv &> /dev/null; then
    echo "uv not found. Installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
else
    echo "uv is already installed."
fi

# === Check for tcsh (required by AFNI installer) ===
if ! command -v tcsh &> /dev/null; then
    echo "tcsh not found. Installing..."
    if command -v conda &> /dev/null; then
        conda install -y -c conda-forge tcsh
    else
        echo "conda not available. Install tcsh manually."
        exit 1
    fi
else
    echo "tcsh is already installed."
fi

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo "jq not found. Installing..."
    if command -v conda &> /dev/null; then
        conda install -y -c conda-forge jq
    else
        echo "No supported package manager found for installing jq."
        exit 1
    fi
else
    echo "jq is already installed."
fi

# === Install AFNI Locally ===
if [ -d "$AFNI_DIR" ] && [ -x "${AFNI_DIR}/afni" ]; then
    echo "AFNI already installed at ${AFNI_DIR}."
else
    echo "Installing AFNI..."
    
    # Install AFNI dependencies
    if command -v apt-get &> /dev/null; then
        echo "Detected apt-get, installing AFNI dependencies..."
        sudo apt-get update
        sudo apt-get install -y libxmu-dev libglu1-mesa-dev libglib2.0-dev libglw1-mesa \
                             libxm4 libxi-dev libxpm-dev libxt-dev
    else
        echo "WARNING: apt-get not found, skipping automatic dependency installation."
        echo "If AFNI fails to run, you may need to manually install dependencies like libGLw.so.1"
    fi
    
    mkdir -p "$AFNI_DIR"
    cd "$AFNI_DIR"
    
    # Download and install AFNI
    echo "Downloading AFNI binaries..."
    curl -O https://afni.nimh.nih.gov/pub/dist/bin/linux_ubuntu_16_64/@update.afni.binaries
    
    echo "Running AFNI installer..."
    tcsh @update.afni.binaries -package linux_ubuntu_16_64 -do_extras -bindir "$PWD"
    
    # Return to original directory
    cd -
    
    # Verify installation
    if [ ! -x "${AFNI_DIR}/afni" ]; then
        echo "ERROR: AFNI installation failed. Executable not found."
        exit 1
    fi
    
    echo "AFNI installed successfully."
fi

# === Install ANTs Locally ===
ants_conda="ants_env"
if conda env list | grep -qE "^${ants_conda}[[:space:]]"; then
    echo "Conda environment '${ants_conda}' already exists. Skipping creation."
else
    echo "Creating and installing ANTs in '${ants_conda}'..."
    conda create -y -n "$ants_conda" -c conda-forge ants
fi

# === Sync Python env with uv ===
uv sync

# === Add ants/afni to UV activate ===

uv_env_act_file=".venv/bin/activate"

if grep -q "Add AFNI" "$uv_env_act_file" && grep -q "Add ANTs from conda env" "$uv_env_act_file"; then
    echo "AFNI and ANTs configurations already exist in $uv_env_act_file."
else
    # Add the configurations to the end of the file
    cat << 'EOF' >> "$uv_env_act_file"

# Add AFNI
export AFNI_DIR="${PROJECT_ROOT}/tools/afni"
export PATH="${AFNI_DIR}:$PATH"
export AFNI_PLUGINPATH="${AFNI_DIR}"

# Add ANTs from conda env
export ANTS_DIR="${HOME}/miniconda3/envs/ants_env"
export PATH="${ANTS_DIR}/bin:$PATH"

echo "AFNI and ANTs installed and available in current shell session."
EOF
    echo "AFNI and ANTs configurations added to $uv_env_act_file."
fi



