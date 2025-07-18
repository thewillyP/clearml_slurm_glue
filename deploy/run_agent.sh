#!/bin/bash
# Parse arguments
RUN_TIME=$1
RUN_CPUS=$2
RUN_MEM=$3
LOG_DIR=$4
SCRATCH_DIR=$5
FORCE_REBUILD=${6:-false}

IMAGE_PATH="${SCRATCH_DIR}/clearml_agent.sif"

# Check if we should build the image
if [ "$FORCE_REBUILD" = "true" ] || [ ! -f "${IMAGE_PATH}" ]; then
    echo "Force rebuild requested. Building image..."
    singularity build --force "${IMAGE_PATH}" docker://thewillyp/clearml-agent
else
    echo "Image found at ${IMAGE_PATH}. Skipping build."
fi

# Submit the SLURM job
sbatch <<EOF
#!/bin/bash
#SBATCH --job-name=clearml_agent
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --mem=${RUN_MEM}
#SBATCH --time=${RUN_TIME}
#SBATCH --cpus-per-task=${RUN_CPUS}
#SBATCH --output=${LOG_DIR}/clearml-agent-%j.log
#SBATCH --error=${LOG_DIR}/clearml-agent-%j.err

set -euo pipefail

# Get ClearML credentials from AWS Parameter Store
CLEARML_API_ACCESS_KEY=\$(singularity run --cleanenv \\
    --env AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID},AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY},AWS_DEFAULT_REGION=us-east-1 \\
    docker://amazon/aws-cli \\
    ssm get-parameter --name "/dev/research/clearml_api_access_key" --with-decryption --query Parameter.Value --output text)

CLEARML_API_HOST=\$(singularity run --cleanenv \\
    --env AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID},AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY},AWS_DEFAULT_REGION=us-east-1 \\
    docker://amazon/aws-cli \\
    ssm get-parameter --name "/dev/research/clearml_api_host" --query Parameter.Value --output text)

CLEARML_API_SECRET_KEY=\$(singularity run --cleanenv \\
    --env AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID},AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY},AWS_DEFAULT_REGION=us-east-1 \\
    docker://amazon/aws-cli \\
    ssm get-parameter --name "/dev/research/clearml_api_secret_key" --with-decryption --query Parameter.Value --output text)

CLEARML_FILES_HOST=\$(singularity run --cleanenv \\
    --env AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID},AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY},AWS_DEFAULT_REGION=us-east-1 \\
    docker://amazon/aws-cli \\
    ssm get-parameter --name "/dev/research/clearml_files_host" --query Parameter.Value --output text)

CLEARML_WEB_HOST=\$(singularity run --cleanenv \\
    --env AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID},AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY},AWS_DEFAULT_REGION=us-east-1 \\
    docker://amazon/aws-cli \\
    ssm get-parameter --name "/dev/research/clearml_web_host" --query Parameter.Value --output text)

# Run ClearML agent with singularity
singularity exec --cleanenv --containall \\
    --env AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID} \\
    --env AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY} \\
    --env AWS_DEFAULT_REGION=us-east-1 \\
    --env CLEARML_API_HOST=\${CLEARML_API_HOST} \\
    --env CLEARML_WEB_HOST=\${CLEARML_WEB_HOST} \\
    --env CLEARML_FILES_HOST=\${CLEARML_FILES_HOST} \\
    --env CLEARML_API_ACCESS_KEY=\${CLEARML_API_ACCESS_KEY} \\
    --env CLEARML_API_SECRET_KEY=\${CLEARML_API_SECRET_KEY} \\
    --env CLEARML_AGENT_FORCE_UV=1 \\
    --bind \${SLURM_TMPDIR}:/tmp \\
    --bind \${SLURM_TMPDIR}:\${HOME} \\
    ${IMAGE_PATH} \\
    clearml-agent daemon --queue infrastructure

EOF